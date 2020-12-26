import asyncio
import dataclasses
import logging
import socket
from dataclasses import dataclass
from typing import ClassVar, List, Optional

from multimethod import multimethod

import loveletter_multiplayer.networkcomms.message as msg
from loveletter.game import Game
from loveletter_multiplayer.networkcomms import (
    ConnectionClosedError,
    Message,
    MessageDeserializer,
    MessageSerializer,
    ProtocolError,
    RestartSession,
    UnexpectedMessageError,
    receive_message,
    send_message,
)
from loveletter_multiplayer.utils import (
    Address,
    InnerClassMeta,
    close_stream_at_exit,
    format_exception,
)


LOGGER = logging.getLogger(__name__)

ClientSessions = List["LoveletterPartyServer.ClientSessionManager"]


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

        self._client_sessions: ClientSessions = []
        self._party_host_username = party_host_username

        self._serializer = MessageSerializer()
        self._deserializer = MessageDeserializer()

        # to be initialized in self._init_async:
        self._server: asyncio.AbstractServer
        self._sessions_lock: asyncio.Lock
        self._ready_to_play: asyncio.Event
        self._game_ready: asyncio.Event
        self._server_task: Optional[asyncio.Task] = None

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
        it = (session.client_info for session in self._client_sessions)
        result = None
        for c in it:
            if c.is_host:
                result = c
                break
        for c in it:
            assert not c.is_host, "More than one party host"
        return result

    @property
    def party_host_session(self) -> Optional["ClientSessionManager"]:
        client = self.party_host
        return self._client_sessions[client.id] if client is not None else None

    async def run_server(self):
        await self._init_async()
        self._server_task = asyncio.current_task()
        async with self._server:
            asyncio.create_task(
                self.create_game_when_ready(), name="start_game_when_ready"
            )
            try:
                await self._server.serve_forever()
            finally:
                LOGGER.info("Server shutting down")
                self._server_task = None

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
            address = writer.get_extra_info("peername")
            task = asyncio.current_task()
            task.set_name(f"<connection handler for {address}>")

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

                LOGGER.info(f"Received connection from %s", address)
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
                    LOGGER.critical(
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
            self._session_task = None
            self._receive_loop_task = None
            self._game_message_queue = asyncio.Queue()

        def __repr__(self):
            return f"<session manager for {self.client_info}>"

        def __enter__(self):
            if self not in self.server._client_sessions:
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
            self._session_task = asyncio.current_task()
            self._receive_loop_task = asyncio.create_task(
                self._receive_loop(), name="receive_loop"
            )
            while True:
                try:
                    await self.server._game_ready.wait()
                    await self._receive_loop_task
                    return
                except RestartSession as exc:
                    await self._send_error_response(
                        msg.Error.Code.RESTART_SESSION, str(exc)
                    )
                    continue

        async def abort(self):
            """Abort this session."""
            LOGGER.info("Aborting session with %s", self.client_info)
            current_task = asyncio.current_task()
            for task in self._receive_loop_task, self._session_task:
                if task is current_task:
                    raise RuntimeError(f"Can't abort from within {task}")
                task.cancel()
                try:
                    await task  # wait for the task to die
                except asyncio.CancelledError:
                    pass

        async def send_message(self, message: Message):
            await self.server.send_message(self.writer, message)

        async def receive_message(self) -> Message:
            return await self.server.receive_message(self.reader)

        @multimethod
        async def handle_message(self, message: msg.Message):
            raise NotImplementedError

        @handle_message.register
        async def handle_message(self, message: msg.Error):
            raise NotImplementedError

        # noinspection PyUnusedLocal
        @handle_message.register
        async def handle_message(self, message: msg.Logon):
            LOGGER.warning("Received duplicate logon from %s", self.client_info)
            await self._send_error_response(
                msg.Error.Code.LOGON_ERROR,
                "Can only log on to the party once",
            )

        # noinspection PyUnusedLocal
        @handle_message.register
        async def handle_message(self, message: msg.ReadyToPlay):
            if self.client_info.is_host:
                self.server._ready_to_play.set()
                # reply will be sent by create_game_when_ready
            else:
                await self._reply_permission_denied(message)

        @handle_message.register
        async def handle_message(self, message: msg.ReadRequest):
            attrs = message.request.split(".")[::-1]
            try:
                obj = self.server
                while attrs:
                    obj = getattr(obj, attrs.pop())
            except AttributeError as e:
                await self._send_error_response(
                    msg.Error.Code.ATTRIBUTE_ERROR,
                    format_exception(e),
                )
                return

            message = msg.DataMessage(obj)
            try:
                await self.send_message(message)
            except TypeError:
                await self._send_error_response(
                    msg.Error.Code.SERIALIZE_ERROR,
                    reason="Requested object can't be serialized",
                )
                return

        @handle_message.register
        async def handle_message(self, message: msg.FulfilledGameInputMessage):
            await self._game_message_queue.put(message)

        async def _receive_loop(self):
            cancelled = False
            try:
                while True:
                    message = await self.receive_message()
                    if not message:
                        break
                    LOGGER.debug(
                        "Received a message from %s: %s", self.client_info, message
                    )
                    asyncio.create_task(
                        self.handle_message(message), name="handle_message"
                    )

                LOGGER.info("Client closed the connection: %s", self.client_info)
            except ConnectionResetError:
                LOGGER.warning(
                    "Connection forcibly closed by client: %s", self.client_info
                )
            except asyncio.CancelledError:
                cancelled = True
                raise
            finally:
                if not cancelled:
                    asyncio.create_task(
                        self._connection_closed_by_client(),
                        name="connection_closed_handler",
                    )

        async def _reply_ok(self):
            await self.server._reply_ok(self.writer)

        async def _send_error_response(self, code, reason):
            await self.server._send_error_response(self.writer, code, reason)

        async def _reply_permission_denied(self, cause):
            LOGGER.warning(
                "Received unauthorized request form %s: ", self.client_info, cause
            )
            await self._send_error_response(
                msg.Error.Code.PERMISSION_DENIED, reason="Only the host can do this"
            )

        async def _connection_closed_by_client(self):
            """Callback for when the connection is closed/reset from the client side."""
            LOGGER.debug(f"Handling connection closed by client {self.client_info}")
            await self.abort()
            server = self.server
            if self.client_info.is_host:
                # host left; abort all sessions
                reason = "Host disconnected"
                await server._abort_server(reason)
            elif server._ready_to_play.is_set():
                # a game was in progress;
                # for now just abort the game and restart all sessions
                server._abort_current_game(
                    f"Player {self.client_info.username} disconnected"
                )

    async def create_game_when_ready(self):
        while True:
            try:
                await self._ready_to_play.wait()
                LOGGER.debug("Received ready to play signal")
                # acquire lock to make sure the number of connected clients is final
                # (there could be one last client in the process of connecting)
                async with self._sessions_lock:
                    usernames = [
                        session.client_info.username
                        for session in self._client_sessions
                    ]
                self.game = Game(usernames)
                LOGGER.info("Ready to play; created game: %s", self.game)
                message = msg.GameCreated(self.game.players)
                tasks = (s.send_message(message) for s in self._client_sessions)
                await asyncio.gather(*tasks)
                self._game_ready.set()
                break
            except Exception as e:
                LOGGER.error("Exception while trying to create game", exc_info=e)
                self._ready_to_play.clear()
                await self._send_error_response(
                    self.party_host_session.writer,
                    msg.Error.Code.EXCEPTION,
                    f"Exception while trying to create game: {format_exception(e)}",
                )
                continue

    async def send_message(self, writer: asyncio.StreamWriter, message: Message):
        await send_message(writer, message, serializer=self._serializer)

    async def receive_message(self, reader: asyncio.StreamReader) -> Message:
        return await receive_message(reader, deserializer=self._deserializer)

    async def _refuse_connection(
        self,
        writer,
        *,
        reason: str,
        error_code: msg.Error.Code = msg.Error.Code.CONNECTION_REFUSED,
    ):
        address = writer.get_extra_info("peername")
        LOGGER.info(f"Refusing connection from %s (%s)", address, reason)
        await self._send_error_response(writer, error_code, reason)
        writer.write_eof()

    def _attach(self, session: ClientSessionManager):
        # this context manager is not async so no need to lock read/write accesses
        LOGGER.info("Starting session for %s", session.client_info)
        address = session.client_info.address
        if address in (s.client_info.address for s in self._client_sessions):
            raise RuntimeError("There is already a session for %s", address)
        object.__setattr__(session.client_info, "id", len(self._client_sessions))
        self._client_sessions.append(session)
        session._attached = True
        return session

    def _detach(self, session: ClientSessionManager):
        address = session.client_info.address
        if session not in self._client_sessions:
            raise RuntimeError(
                "Trying to detach an already detached connection %s", address
            )
        self._client_sessions.remove(session)
        session._attached = False
        LOGGER.info(f"Session with %s has ended", session.client_info)

    async def _receive_logon(self, reader, writer) -> "ClientInfo":
        address = Address(*writer.get_extra_info("peername"))

        try:
            # need a timeout because we're holding a lock that is blocking other conns.
            message = await asyncio.wait_for(self.receive_message(reader), timeout=3.0)
        except asyncio.TimeoutError:
            LOGGER.warning("Client at %s: logon timed out", address)
            raise
        if message is None:
            LOGGER.warning(
                "Client at %s closed the connection before logging on",
                address,
            )
            raise ConnectionClosedError
        if not isinstance(message, msg.Logon):
            LOGGER.warning(
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

        await self._reply_ok(writer)
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

    async def _reply_ok(self, writer):
        message = msg.OkMessage()
        await self.send_message(writer, message)

    async def _send_error_response(self, writer, code, reason):
        address = writer.get_extra_info("peername")
        message = msg.Error(code, reason)
        LOGGER.debug("Sending error response to %s: %s", address, message)
        await self.send_message(writer, message)

    def _abort_current_game(self, reason: str):
        server = self
        LOGGER.warning(
            f"Aborting game and restarting remaining sessions "
            f"({len(self._client_sessions)})"
        )
        server.game = None
        server._ready_to_play.clear()
        server._game_ready.clear()
        exc = RestartSession(reason)
        for session in server._client_sessions:
            coro = session._session_task.get_coro()
            coro.throw(exc)
        asyncio.create_task(self.create_game_when_ready(), name="start_game_when_ready")

    async def _abort_server(self, reason: str):
        LOGGER.critical("Aborting server: %s", reason)
        for session in self._client_sessions:
            await session._send_error_response(msg.Error.Code.SESSION_ABORTED, reason)
            await session.abort()
        self._server_task.cancel()


@dataclass(frozen=True)
class ClientInfo:
    address: Address
    id: Optional[int]
    username: Optional[str]
    is_host: bool = False  # host of the party; has privileges to configure the server
