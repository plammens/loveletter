import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import loveletter_multiplayer.networkcomms.message as msg
from loveletter.utils.misc import minirepr
from loveletter_multiplayer.networkcomms import (
    ConnectionClosedError,
    Message,
    UnexpectedMessageError,
    receive_message,
    send_message,
)
from loveletter_multiplayer.remoteobj import RemoteGameShadowCopy
from loveletter_multiplayer.utils import Address, InnerClassMeta, close_stream_at_exit


LOGGER = logging.getLogger(__name__)


class LoveletterClient:
    username: str

    def __init__(self, username: str, is_host: bool = False):
        self.username = username
        self.is_host = is_host

        self._server_conn: Optional[LoveletterClient.ServerConnectionManager] = None

    @property
    def game(self) -> Optional[RemoteGameShadowCopy]:
        return self._server_conn.game if self._server_conn is not None else None

    __repr__ = minirepr

    async def connect(self, host, port):
        reader, writer = await asyncio.open_connection(host=host, port=port)
        async with close_stream_at_exit(writer):
            address = writer.get_extra_info("peername")
            LOGGER.info(f"Successfully connected to {address}")

            server_info = ServerInfo(address)
            # noinspection PyArgumentList
            with self.ServerConnectionManager(server_info, reader, writer) as conn:
                try:
                    await conn.manage()
                except Exception as exc:
                    LOGGER.error(
                        "Unhandled exception in %s",
                        conn,
                        exc_info=exc,
                    )
                    # the client does raise; indeed the caller can retry connecting
                    raise

    async def ready(self):
        """Send a message to the server indicating that this client is ready to play."""
        if self.is_host:
            message = msg.ReadyToPlay()
            await send_message(self._server_conn.writer, message)
        else:
            pass  # for now just ignore this

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

        game: Optional[RemoteGameShadowCopy]

        def __init__(
            self, client: "LoveletterClient", server_info: "ServerInfo", reader, writer
        ):
            self.client: LoveletterClient = client
            self.server_info = server_info
            self.reader: asyncio.StreamReader = reader
            self.writer: asyncio.StreamWriter = writer
            self.game = None

        def __repr__(self):
            return f"<connection from {self.client} to {self.server_info}>"

        def __enter__(self):
            LOGGER.info("Activating %s", self)
            if self.client._server_conn is not None:
                raise RuntimeError("There is already an active connection")
            self.client._server_conn = self
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.client._server_conn = None
            LOGGER.info("Deactivated %s", self)

        async def manage(self):
            if self.client._server_conn is not self:
                raise RuntimeError("Can't manage a detached connection")
            await self._logon()
            await self._wait_for_game()
            await self._receive_loop()

        async def request(self, message: Message) -> Message:
            """
            Send a request to the server and await for the reply.

            Raises a ConnectionError if the server closes the connection without
            sending a response.

            :param message: Any message that expects a reply.
            :return: The response from the server.
            """
            await send_message(self.writer, message)
            response = await self._expect_message(timeout=5.0)
            return response

        async def _expect_message(
            self,
            timeout: Optional[float] = None,
            message_type: Optional[Message.Type] = None,
        ) -> Message:
            """
            Wait for an expected message from the server.

            Raises a ConnectionError if the server closes the connection without
            sending a message.

            :param timeout: Optional timeout for receiving a message.
            :param message_type: If not None, check that the received message is of that
                                 type.
            """
            message = await asyncio.wait_for(receive_message(self.reader), timeout)
            if message is None:
                raise ConnectionClosedError(
                    "Server closed the connection while expecting a message"
                )
            if message_type is not None and not message.type == message_type:
                raise UnexpectedMessageError(
                    f"Expected {message_type.name}, got {message}"
                )
            return message

        async def _logon(self):
            """Identify oneself to the server."""
            message = msg.Logon(self.client.username)
            response = await self.request(message)
            if response.type != Message.Type.OK:
                raise RuntimeError(f"Logon failed, received response: {response}")

        async def _wait_for_game(self):
            """Wait for the server to create the game."""
            # noinspection PyTypeChecker
            message: msg.GameCreated = await self._expect_message(
                message_type=Message.Type.GAME_CREATED
            )
            LOGGER.info("Remote game created; creating local copy")
            self.game = RemoteGameShadowCopy.from_server_message(message)

        async def _receive_loop(self):
            while True:
                message = await receive_message(self.reader)
                if not message:
                    break
                LOGGER.debug(
                    "%s received a message from the server: %s", self.client, message
                )

            LOGGER.info("Server closed the connection to %s", self.client)


@dataclass(frozen=True)
class ServerInfo:
    address: Address
