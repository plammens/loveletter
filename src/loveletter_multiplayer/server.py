import asyncio
import dataclasses
import logging
import socket
from dataclasses import dataclass
from typing import ClassVar, Dict, Optional

from multimethod import multimethod

import loveletter_multiplayer.networkcomms.message as msg
from loveletter.game import Game
from loveletter_multiplayer.networkcomms import (
    ConnectionClosedError,
    MessageDeserializer,
    MessageSerializer,
    ProtocolError,
    UnexpectedMessageError,
    receive_message,
    send_message,
)
from loveletter_multiplayer.utils import (
    Address,
    InnerClassMeta,
    close_stream_at_exit,
)


logger = logging.getLogger(__name__)

ClientSessions = Dict[Address, "LoveletterPartyServer.ClientSessionManager"]


class LoveletterPartyServer:
    """
    A server for a party of Love Letter.

    A party is a group of physical players that is going to play a game together.

    The maximum number of clients this can serve is the maximum amount of players
    allowed in a game. After this number is reached, any further connections will be
    sent an error message and will be subsequently closed.
    """

    MAX_CLIENTS: ClassVar[int] = Game.MAX_PLAYERS

    host: str
    port: int
    game: Optional[Game]

    def __init__(self, host, port, party_host_username: str):
        """

        :param host: IP (or domain name) to bind the server to.
        :param port: Port number to bind the server to.
        :param party_host_username: The username of the player that will host this party
                                    (has additional privileges to configure the party).
        """
        self.host = host
        self.port = port
        self.game = None

        self._client_sessions: ClientSessions = {}
        self._party_host_username = party_host_username

        self._serializer = MessageSerializer()
        self._deserializer = MessageDeserializer()

        # to be initialized in self._init_async:
        self._server: asyncio.AbstractServer
        self._sessions_lock: asyncio.Lock
        self._ready_to_play: asyncio.Event
        self._game_ready: asyncio.Event

    async def _init_async(self):
        """Initialize asyncio-related attributes that need an active event loop."""
        self._server = await asyncio.start_server(
            self.connection_handler,
            host=self.host,
            port=self.port,
            backlog=self.MAX_CLIENTS + 5,  # allow some space to handle excess connects
            start_serving=False,
        )
        self._sessions_lock = asyncio.Lock()
        self._ready_to_play = asyncio.Event()
        self._game_ready = asyncio.Event()

    @property
    def num_connected_clients(self) -> int:
        """The number of clients currently being served by the server."""
        return len(self._client_sessions)

    @property
    def party_host(self) -> Optional["ClientInfo"]:
        """Get the ClientInfo corresponding to the host of this party, if present."""
        it = (session.client_info for session in self._client_sessions.values())
        result = None
        for c in it:
            if c.is_host:
                result = c
                break
        for c in it:
            assert not c.is_host, "More than one party host"
        return result

    async def run_server(self):
        await self._init_async()
        async with self._server:
            asyncio.create_task(
                self._start_game_when_ready(), name="start_game_when_ready"
            )
            await self._server.serve_forever()

    async def connection_handler(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """
        Socket connection callback for :func:`asyncio.start_server`.

        This just decides whether to accept or refuse the connection (at the logical
        level, since at the socket level the connection has already been established
        at this point). If the connection is accepted, a ClientSessionManager is
        created and set off to handle the connection. Otherwise, an error message is
        sent to the connected client and the connection is shut down and closed.
        """
        async with close_stream_at_exit(writer):
            # hold the lock until we attach the session (or refuse the connection)
            async with self._sessions_lock:
                # Note: if we refuse the connection now, there is no need to wait for
                # the logon message since we would have rejected in any case.
                if self.num_connected_clients >= self.MAX_CLIENTS:
                    return await self._refuse_connection(
                        writer,
                        reason=f"Maximum capacity ({self.MAX_CLIENTS} players) reached",
                    )
                if self._ready_to_play.is_set():
                    return await self._refuse_connection(
                        writer,
                        reason="A game is already in progress",
                    )

                address = writer.get_extra_info("peername")
                logger.info(f"Received connection from %s", address)
                try:
                    client_info = await self._receive_logon(reader, writer)
                except (ProtocolError, asyncio.TimeoutError):
                    return
                # noinspection PyArgumentList
                session = self.ClientSessionManager(client_info, reader, writer)
                # attach before releasing the lock:
                self._attach(session)

            with session:
                try:
                    # where the actual session is managed; this suspends this
                    # coroutine until the session ends in some way
                    await session.manage()
                except Exception as exc:
                    logger.critical(
                        "Unhandled exception in client handler", exc_info=exc
                    )

    class ClientSessionManager(metaclass=InnerClassMeta):
        """
        Manages a single connection with a client.

        When used as a context manager, entering the context represents attaching this
        session to the server and exiting it represents detaching. A session can only
        start being managed if it has been successfully attached to the server.
        """

        def __init__(
            self,
            server: "LoveletterPartyServer",
            client_info: "ClientInfo",
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ):
            self.server = server
            self.reader = reader
            self.writer = writer
            self.client_info = client_info

            self._attached = False
            self._manage_task = None

        def __enter__(self):
            if self.client_info.address not in self.server._client_sessions:
                self.server._attach(self)
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.server._detach(self)

        async def manage(self):
            """
            Manage this client session.

            Can only be called if this session has been attached to the server (i.e.
            it can only be called inside a `with self` block).
            """
            if not self._attached:
                raise RuntimeError("Cannot manage a detached session")
            self._manage_task = asyncio.current_task()
            asyncio.create_task(self._receive_loop(), name="receive_loop")
            await self.server._ready_to_play.wait()

        @multimethod
        async def handle_message(self, message: msg.Message):
            raise NotImplementedError

        @handle_message.register
        async def handle_message(self, message: msg.Error):
            raise NotImplementedError

        @handle_message.register
        async def handle_message(self, message: msg.Logon):
            # the client is identifying themselves
            logging.warning("Received duplicate logon from %s", self.client_info)
            await self._send_error_response(
                msg.Error.Code.LOGON_ERROR,
                "Can only log on to the party once",
            )

        async def _receive_loop(self):
            try:
                while True:
                    message = await receive_message(self.reader)
                    if not message:
                        break
                    logger.debug(
                        "Received a message from %s: %s", self.client_info, message
                    )
                    asyncio.create_task(
                        self.handle_message(message), name="handle_message"
                    )

                logger.info("Client %s closed the connection", self.client_info)
            except ConnectionResetError:
                logger.warning(
                    "Connection from %s forcibly closed by client", self.client_info
                )
            finally:
                self._manage_task.cancel()

        async def _send_error_response(self, code, reason):
            await self.server._send_error_response(self.writer, code, reason)

    async def _start_game_when_ready(self):
        await self._ready_to_play.wait()
        # TODO: instantiate game
        self._game_ready.set()

    async def _refuse_connection(
        self,
        writer,
        *,
        reason: str,
        error_code: msg.Error.Code = msg.Error.Code.CONNECTION_REFUSED,
    ):
        address = writer.get_extra_info("peername")
        logger.info(f"Refusing connection from %s (%s)", address, reason)
        await self._send_error_response(writer, error_code, reason)
        writer.write_eof()

    @staticmethod
    async def _send_error_response(writer, code, reason):
        address = writer.get_extra_info("peername")
        message = msg.Error(code, reason)
        logging.debug("Sending error response to %s: %s", address, message)
        await send_message(writer, message)

    def _attach(self, session: ClientSessionManager):
        # this context manager is not async so no need to lock read/write accesses
        logger.info("Starting session for %s", session.client_info)
        address = session.client_info.address
        if address in self._client_sessions:
            raise RuntimeError("There is already a session for %s", address)
        self._client_sessions[address] = session
        session._attached = True
        return session

    def _detach(self, session: ClientSessionManager):
        address = session.client_info.address
        if address not in self._client_sessions:
            raise RuntimeError(
                "Trying to detach an already detached connection %s", address
            )
        del self._client_sessions[address]
        session._attached = False
        logger.info(f"Session with %s has ended", session.client_info)

    async def _receive_logon(self, reader, writer) -> "ClientInfo":
        address = Address(*writer.get_extra_info("peername"))

        try:
            # need a timeout because we're holding a lock that is blocking other conns.
            message = await asyncio.wait_for(receive_message(reader), timeout=3.0)
        except asyncio.TimeoutError:
            logger.warning("Client at %s: logon timed out", address)
            raise
        if message is None:
            logger.warning(
                "Client at %s closed the connection before logging on",
                address,
            )
            raise ConnectionClosedError
        if not isinstance(message, msg.Logon):
            logger.warning(
                "Expected a logon message from %s, received: %s",
                address,
                message,
            )
            await self._refuse_connection(
                writer, reason="Didn't receive the expected logon message"
            )
            raise UnexpectedMessageError(message)

        client_info = ClientInfo(
            address=address,
            id=len(self._client_sessions),
            username=message.username,
        )
        if self._is_host(client_info):
            client_info = dataclasses.replace(client_info, is_host=True)
        return client_info

    def _is_host(self, client: "ClientInfo") -> bool:
        """
        Check whether a newly connected client is the host of the party.

        The host is determined as the first localhost client with the correct username
        to successfully connect to the server.
        """
        if self.party_host is not None:
            return False  # we already have a host; only one host
        return (
            socket.gethostbyname(client.address.host) == "127.0.0.1"
            and client.username == self._party_host_username
        )


@dataclass(frozen=True)
class ClientInfo:
    address: Address
    id: Optional[int]
    username: Optional[str]
    is_host: bool = False  # host of the party; has privileges to configure the server
