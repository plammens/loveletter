import asyncio
import logging
from asyncio import IncompleteReadError
from typing import Optional

from loveletter.utils.misc import minirepr
from loveletter_multiplayer.networkcomms import MESSAGE_SEPARATOR, MessageDeserializer
from loveletter_multiplayer.utils import InnerClassMeta, close_stream_at_exit

logger = logging.getLogger(__name__)


class LoveletterClient:
    def __init__(self):
        self._server_conn: Optional[LoveletterClient.ServerConnectionManager] = None

        self._deserializer = MessageDeserializer()

    __repr__ = minirepr

    async def connect(self, host, port):
        reader, writer = await asyncio.open_connection(host=host, port=port)
        logger.info(f"Successfully connected to {writer.get_extra_info('peername')}")
        async with close_stream_at_exit(writer):
            # noinspection PyArgumentList
            with self.ServerConnectionManager(reader, writer) as conn:
                try:
                    await conn.manage()
                except Exception as exc:
                    logger.error(
                        "Unhandled exception in %s",
                        conn,
                        exc_info=exc,
                    )
                    # the client does raise; indeed the caller can retry connecting
                    raise

    class ServerConnectionManager(metaclass=InnerClassMeta):
        """
        Manages the connection with the server.

        When used as a context manager, entering the context represents attaching this
        connection to the client, and exiting it represents detaching it. A session
        can only start being managed if it has been successfully been set as the
        client's active connection.

        If, upon entering the context, there is already another active connection,
        an RuntimeError will be raised.
        """

        def __init__(self, client: "LoveletterClient", reader, writer):
            self.client: LoveletterClient = client
            self.reader: asyncio.StreamReader = reader
            self.writer: asyncio.StreamWriter = writer

            self.server_address = writer.get_extra_info("peername")

        def __repr__(self):
            return f"<connection from {self.client} to {self.server_address}>"

        def __enter__(self):
            logger.info("Activating %s", self)
            if self.client._server_conn is not None:
                raise RuntimeError("There is already an active connection")
            self.client._server_conn = self
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.client._server_conn = None
            logger.info("Deactivated %s", self)

        async def manage(self):
            if self.client._server_conn is not self:
                raise RuntimeError("Can't manage a detached connection")
            await self._receive_loop()

        async def _receive_loop(self):
            while True:
                message = await self._receive_one_encoded()
                if not message:
                    break
                message = self.client._deserializer.deserialize(message)
                logger.debug(
                    "%s received a message from the server: %s", self.client, message
                )

            logger.info("Server closed the connection to %s", self.client)

        async def _receive_one_encoded(self) -> bytes:
            """Receive a single message (as bytes); return empty bytes if closed."""
            try:
                return await self.reader.readuntil(MESSAGE_SEPARATOR)
            except IncompleteReadError as incomplete:
                if incomplete.partial == b"":
                    return b""
                else:
                    raise
