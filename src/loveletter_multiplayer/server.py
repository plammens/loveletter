import asyncio
import logging
from typing import ClassVar, Optional

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
        self._client_semaphore = SemaphoreWithCount(value=self.MAX_CLIENTS)
        self._serializer = MessageSerializer()
        self._deserializer = MessageDeserializer()

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
            await server.serve_forever()

    async def connection_handler(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        async with close_stream_at_exit(writer):
            if self._client_semaphore.locked():
                # max clients reached; politely refuse the connection
                await self._refuse_connection(writer)
                return

            async with self._client_semaphore:
                address = writer.get_extra_info("peername")
                logger.info(f"Received connection from %s", address)
                try:
                    # where the actual session is managed
                    await self.ClientSessionManager(self, reader, writer).manage()
                except Exception as e:
                    logger.critical("Unhandled exception in client handler", exc_info=e)
                finally:
                    logger.info(f"Releasing connection from %s", address)

    class ClientSessionManager:
        """Manages a single connection with a client."""

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

        async def manage(self):
            await asyncio.sleep(10)

    async def _refuse_connection(self, writer):
        address = writer.get_extra_info("peername")
        logger.info(f"Refusing connection from %s (limit reached)", address)
        message = ErrorMessage(
            ErrorMessage.Code.MAX_CAPACITY,
            f"Maximum capacity for a party ({self.MAX_CLIENTS}) reached",
        )
        logger.debug(f"Sending refusal message to %s and closing connection", address)
        writer.write(self._serializer.serialize(message))
        await writer.drain()
        writer.write_eof()
