import asyncio
import logging
from typing import ClassVar, List, Optional

from loveletter.game import Game
from loveletter_multiplayer.message import (
    ErrorMessage,
    MessageDeserializer,
    MessageSerializer,
)
from loveletter_multiplayer.utils import SemaphoreWithCount, close_stream_at_exit


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

        self._server: Optional[asyncio.AbstractServer] = None
        self._client_sessions: List[LoveletterPartyServer.ClientSessionManager] = []

        self._serializer = MessageSerializer()
        self._deserializer = MessageDeserializer()

        self._client_semaphore = SemaphoreWithCount(value=self.MAX_CLIENTS)
        self._ready_to_start = asyncio.Event()

    @property
    def num_connected_clients(self) -> int:
        """The number of clients currently being served by the server."""
        return self._client_semaphore.count

    async def run_server(self):
        self._server = server = await asyncio.start_server(
            self.connection_handler,
            host=self.host,
            port=self.port,
            backlog=self.MAX_CLIENTS + 5,  # allow some space to handle excess connects
        )

        async with server:
            asyncio.create_task(self._start_game_when_ready())
            await server.serve_forever()

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
            elif self._ready_to_start.is_set():
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
                with self.ClientSessionManager(self, reader, writer) as session:
                    try:
                        # where the actual session is managed; this suspends this
                        # coroutine until the session ends in some way
                        await session.manage()
                    except Exception as exc:
                        logger.critical(
                            "Unhandled exception in client handler", exc_info=exc
                        )
                    finally:
                        logger.info(f"Releasing connection from %s", address)

    class ClientSessionManager:
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
            self.client_address = writer.get_extra_info("peername")

            self._attached = False

        def __enter__(self):
            logging.info("Starting session for %s", self.client_address)
            self.server._client_sessions.append(self)
            self._attached = True
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            logging.info(f"Session with %s has ended", self.client_address)
            self.server._client_sessions.remove(self)
            self._attached = False

        async def manage(self):
            """
            Manage this client session.

            Can only be called if this session has been attached to the server (i.e.
            it can only be called inside a `with self` block).
            """
            if not self._attached:
                raise RuntimeError("Cannot manage a detached session")
            await self.server._ready_to_start.wait()

    async def _start_game_when_ready(self):
        await self._ready_to_start.wait()

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
        logger.debug(f"Sending refusal message to %s and closing connection", address)
        writer.write(self._serializer.serialize(message))
        await writer.drain()
        writer.write_eof()
