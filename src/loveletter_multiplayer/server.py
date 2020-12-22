import asyncio
import logging
from dataclasses import dataclass
from typing import ClassVar, List, Optional, Tuple

from loveletter.game import Game
from loveletter_multiplayer.networkcomms import (
    ErrorMessage,
    MessageDeserializer,
    MessageSerializer,
    receive_message,
    send_message,
)
from loveletter_multiplayer.utils import (
    InnerClassMeta,
    SemaphoreWithCount,
    close_stream_at_exit,
)


logger = logging.getLogger(__name__)


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

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.game = None

        self._client_sessions: List[LoveletterPartyServer.ClientSessionManager] = []
        self._has_host = False

        self._serializer = MessageSerializer()
        self._deserializer = MessageDeserializer()

        # to be initialized in self._init_async:
        self._server: asyncio.AbstractServer
        self._client_semaphore: SemaphoreWithCount
        self._ready_to_play: asyncio.Event
        self._game_ready: asyncio.Event

    @property
    def num_connected_clients(self) -> int:
        """The number of clients currently being served by the server."""
        return self._client_semaphore.count

    async def run_server(self):
        await self._init_async()
        async with self._server:
            asyncio.create_task(self._start_game_when_ready())
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
            if self._client_semaphore.locked():
                # max clients reached; politely refuse the connection
                return await self._refuse_connection(
                    writer,
                    reason=f"Maximum capacity ({self.MAX_CLIENTS} players) reached",
                )
            elif self._ready_to_play.is_set():
                # game already started or in process of starting; refuse other conns.
                return await self._refuse_connection(
                    writer,
                    reason="A game is already in progress",
                )

            async with self._client_semaphore:
                # note: we use an additional semaphore instead of just checking the
                # count of active sessions (``len(self._client_sessions)``) because
                # it is more robust; consider what would happen if an ``await`` were
                # added before the session is instantiated and attached (the ``with``
                # statement below).

                address = writer.get_extra_info("peername")
                logger.info(f"Received connection from %s", address)
                # noinspection PyArgumentList
                with self.ClientSessionManager(reader, writer) as session:
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
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ):
            self.server = server
            self.reader = reader
            self.writer = writer
            self.client_info = self._make_client_info(writer)

            self._attached = False
            self._manage_task = None

        def __enter__(self):
            logger.info("Starting session for %s", self.client_info)
            self.server._client_sessions.append(self)
            self._attached = True
            if self.client_info.is_host:
                self.server._has_host = True
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.server._client_sessions.remove(self)
            self._attached = False
            if self.client_info.is_host:
                self.server._has_host = False
            logger.info(f"Session with %s has ended", self.client_info)

        def _make_client_info(self, writer: asyncio.StreamWriter) -> "ClientInfo":
            address = writer.get_extra_info("peername")
            client = ClientInfo(address, False)
            client.is_host = self.server._is_host(client)
            return client

        async def manage(self):
            """
            Manage this client session.

            Can only be called if this session has been attached to the server (i.e.
            it can only be called inside a `with self` block).
            """
            if not self._attached:
                raise RuntimeError("Cannot manage a detached session")
            self._manage_task = asyncio.current_task()
            asyncio.create_task(self._receive_loop())
            await self.server._ready_to_play.wait()

        async def _receive_loop(self):
            try:
                while True:
                    message = await receive_message(self.reader)
                    if not message:
                        break
                    logger.debug(
                        "Received a message from %s: %s", self.client_info, message
                    )

                logger.info("Client %s closed the connection", self.client_info)
            except ConnectionResetError:
                logger.warning(
                    "Connection from %s forcibly closed by client", self.client_info
                )
            finally:
                self._manage_task.cancel()

    async def _init_async(self):
        """Initialize asyncio-related attributes that need an active event loop."""
        self._server = await asyncio.start_server(
            self.connection_handler,
            host=self.host,
            port=self.port,
            backlog=self.MAX_CLIENTS + 5,  # allow some space to handle excess connects
            start_serving=False,
        )
        self._client_semaphore = SemaphoreWithCount(value=self.MAX_CLIENTS)
        self._ready_to_play = asyncio.Event()
        self._game_ready = asyncio.Event()

    async def _start_game_when_ready(self):
        await self._ready_to_play.wait()
        # TODO: instantiate game
        self._game_ready.set()

    async def _refuse_connection(
        self,
        writer,
        *,
        reason: str,
        error_code: ErrorMessage.Code = ErrorMessage.Code.CONNECTION_REFUSED,
    ):
        address = writer.get_extra_info("peername")
        logger.info(f"Refusing connection from %s (%s)", address, reason)
        message = ErrorMessage(error_code, reason)
        await send_message(writer, message)
        writer.write_eof()

    def _is_host(self, client: "ClientInfo") -> bool:
        """
        Check whether a newly connected client is the host of the party.

        The host is determined as the first localhost client to successfully
        connect to the server.
        """
        if self._has_host:
            return False  # we already have a host; only one host
        return client.address[0] == "127.0.0.1"


@dataclass
class ClientInfo:
    address: Tuple[str, int]
    is_host: bool = False  # host of the party; has privileges to configure the server
    username: Optional[str] = None

    @property
    def has_logged_on(self):
        """Whether the client has identified themselves to the server."""
        return self.username is not None

    def __repr__(self):
        username, is_host = self.username, self.is_host
        return (
            f"<client with {username=}, {is_host=}>"
            if self.has_logged_on
            else f"<unidentified client at {self._format_address(self.address)}>"
        )

    @staticmethod
    def _format_address(address):
        host, port = address
        return f"{host}:{port}"
