import asyncio
from typing import ClassVar, Optional

from loveletter.game import Game
from loveletter_multiplayer.message import (
    ErrorMessage,
    MessageDeserializer,
    MessageSerializer,
)
from loveletter_multiplayer.utils import SemaphoreWithCount


HOST = ""
PORT = 48888


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
    backend: Optional[asyncio.AbstractServer]
    game: Optional[Game]

    def __init__(self, host=HOST, port=PORT):
        self.host = host
        self.port = port
        self.backend = None
        self.game = None

        self._client_semaphore = SemaphoreWithCount(value=self.MAX_CLIENTS)
        self._serializer = MessageSerializer()
        self._deserializer = MessageDeserializer()

    @property
    def num_connected_clients(self) -> int:
        """The number of clients currently being served by the server."""
        return self._client_semaphore.count

    async def run_server(self):
        self.backend = server = await asyncio.start_server(
            self.client_handler,
            host=self.host,
            port=self.port,
            backlog=self.MAX_CLIENTS + 5,  # allow some space to handle excess connects
        )

        async with server:
            await server.serve_forever()

    async def client_handler(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        address = writer.get_extra_info("peername")
        if self._client_semaphore.locked():
            # max clients reached; politely refuse the connection
            print(f"Refusing connection from {address}")
            message = ErrorMessage(
                ErrorMessage.Code.MAX_CAPACITY,
                f"Maximum capacity for a party ({self.MAX_CLIENTS}) reached",
            )
            writer.write(self._serializer.serialize(message))
            await writer.drain()
            writer.write_eof()
            return

        async with self._client_semaphore:
            print(f"Received connection from {address}")
            await asyncio.sleep(10)
            print(f"Releasing connection from {address}")
            writer.write_eof()


if __name__ == "__main__":
    asyncio.run(LoveletterPartyServer(HOST, PORT).run_server())
