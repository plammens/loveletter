import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Optional, Type, TypeVar

from multimethod import multimethod

import loveletter_multiplayer.networkcomms.message as msg
from loveletter_multiplayer.networkcomms import (
    ConnectionClosedError,
    Message,
    MessageDeserializer,
    RestartSession,
    UnexpectedMessageError,
    fill_placeholders,
    receive_message,
    send_message,
)
from loveletter_multiplayer.remotegame import RemoteGameShadowCopy
from loveletter_multiplayer.utils import Address, InnerClassMeta, close_stream_at_exit


LOGGER = logging.getLogger(__name__)


class LoveletterClient:
    username: str

    def __init__(self, username: str, is_host: bool = False):
        # TODO: subclass with host/guest
        self.username = username
        self.is_host = is_host

        self._server_conn: Optional[LoveletterClient.ServerConnectionManager] = None
        self._connection_task: Optional[asyncio.Task] = None

    @property
    def game(self) -> Optional[RemoteGameShadowCopy]:
        return self._server_conn.game if self._server_conn is not None else None

    def __repr__(self):
        username, is_host = self.username, self.is_host
        return f"<{self.__class__.__name__} with {username=}, {is_host=}>"

    async def connect(self, host, port):
        # TODO: manage logon here
        reader, writer = await asyncio.open_connection(host=host, port=port)
        return asyncio.create_task(self._handle_connection(reader, writer))

    async def send_shutdown(self):
        if not self.is_host:
            raise ValueError("Guest client can't send shutdown message")
        if self._server_conn is None or self._connection_task is None:
            raise RuntimeError("No active connection")
        LOGGER.info("Sending shutdown message to server")
        await self._server_conn._send_message(msg.Shutdown())
        await self._connection_task  # wait for the connection to shut down

    async def _handle_connection(self, reader, writer):
        async with close_stream_at_exit(writer):
            if self._connection_task is not None:
                raise RuntimeError("_handle_connection already called")
            self._connection_task = asyncio.current_task()

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
            await self._server_conn._send_message(message)
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

            self._reset_game_vars()
            self._main_task: Optional[asyncio.Task] = None
            self._receive_loop_active = False

        def _reset_game_vars(self):
            self.game = None
            self._deserializer = MessageDeserializer()

        async def _init_async(self):
            self._game_message_queue = asyncio.Queue()
            self._other_message_queue = asyncio.Queue()

        @property
        def attached(self):
            return self.client._server_conn is self

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
            await self._init_async()
            task = asyncio.current_task()
            task.set_name(f"client<{self.client.username}>")
            if not self.attached:
                raise RuntimeError("Can't manage a detached connection")
            await self._logon()
            while True:
                try:
                    await self._wait_for_game()
                    await self._receive_loop()
                    return
                except RestartSession:
                    LOGGER.info("Restarting session")
                    self._reset_game_vars()
                    continue

        M = TypeVar("M", bound=Message)

        async def request(
            self, message: Message, message_type: Optional[Type[M]] = None
        ) -> M:
            """
            Send a request to the server and await for the reply.

            Raises a ConnectionError if the server closes the connection without
            sending a response.

            :param message: Any message that expects a reply.
            :param message_type: The type of response that is expected. If None, it will
                                 be attempted to deduce from the request type.
            :return: The response from the server.
            """
            await self._send_message(message)
            receiver = (
                self._get_message_from_queue(self._other_message_queue)
                if self._receive_loop_active
                else None
            )
            if message_type is None:
                request_to_response = {msg.ReadRequest: msg.DataMessage}
                # noinspection PyTypeChecker
                message_type = request_to_response.get(type(message), None)
            response = await self._expect_message(
                timeout=5.0, receiver=receiver, message_type=message_type
            )
            return response

        async def get_game_message(self, message_type: Optional[Type[M]] = None) -> M:
            """
            Receive a game message.

            :param message_type: Expected message (sub-)type, if any.
            """
            # noinspection PyTypeChecker
            message: msg.GameMessage = await self._get_message_from_queue(
                self._game_message_queue
            )
            message = fill_placeholders(message, self.game)
            if message_type is not None and not isinstance(message, message_type):
                raise UnexpectedMessageError(
                    f"Expected {message_type.__name__} as game message, got {message}"
                )
            LOGGER.debug("Got game message: %s", message)
            return message

        async def _send_message(self, message: Message) -> None:
            await send_message(self.writer, message)

        async def _receive_message(self) -> Message:
            return await receive_message(self.reader, deserializer=self._deserializer)

        async def _expect_message(
            self,
            timeout: Optional[float] = None,
            message_type: Optional[Type[Message]] = None,
            receiver: Optional[Awaitable[Message]] = None,
        ) -> Message:
            """
            Wait for an expected message from the server.

            Raises a ConnectionError if the server closes the connection without
            sending a message.

            :param timeout: Optional timeout for receiving a message.
            :param message_type: If not None, check that the received message is of that
                                 type.
            :param receiver: Awaitable that will receive a message from the connection
                             when awaited. The default uses :meth:`_receive_message`.
            """
            receiver = receiver or self._receive_message()
            message: Message = await asyncio.wait_for(receiver, timeout)
            if message is None:
                raise ConnectionClosedError(
                    "Server closed the connection while expecting a message"
                )
            self._maybe_raise(message)
            if message_type is not None and not isinstance(message, message_type):
                raise UnexpectedMessageError(
                    f"Expected {message_type.__name__}, got {message}"
                )
            return message

        @staticmethod
        def _maybe_raise(message: Message):
            if (
                isinstance(message, msg.Error)
                and message.error_code == msg.Error.Code.RESTART_SESSION
            ):
                LOGGER.error("Received signal to restart session: %s", message.message)
                raise RestartSession(message.message)

        async def _logon(self):
            """Identify oneself to the server."""
            message = msg.Logon(self.client.username)
            response = await self.request(message)
            if not isinstance(response, msg.OkMessage):
                raise RuntimeError(f"Logon failed, received response: {response}")

        async def _wait_for_game(self):
            """Wait for the server to create the game."""
            self.game = await RemoteGameShadowCopy.from_connection(self)
            self._deserializer = MessageDeserializer(
                game=self.game, fill_placeholders=False
            )

        @multimethod
        async def handle_message(self, message):
            await self._other_message_queue.put(message)
            LOGGER.debug("Put in other message queue: %s", message)

        @handle_message.register
        async def handle_message(self, message: msg.Error):
            LOGGER.error("Error message from server: %s", message)
            self._maybe_raise(message)

        @handle_message.register
        async def handle_message(self, message: msg.GameMessage):
            await self._game_message_queue.put(message)
            LOGGER.debug("Put in game message queue: %s", message)

        async def _receive_loop(self):
            self._receive_loop_active = True
            try:
                while True:
                    message = await self._receive_message()
                    if not message:
                        break
                    LOGGER.info("Received a message from the server: %s", message)
                    # noinspection PyTypeChecker
                    self._maybe_raise(message)
                    asyncio.create_task(
                        self.handle_message(message), name="handle_message"
                    )
            except ConnectionResetError:
                LOGGER.critical("Server forcefully closed the connection")
                raise
            else:
                LOGGER.info("Server closed the connection")
            finally:
                self._receive_loop_active = False
                self._handle_connection_closed_by_server()

        async def _get_message_from_queue(self, queue: asyncio.Queue) -> Message:
            if not self._receive_loop_active or queue is None:
                raise ConnectionClosedError("Receiver is no longer active")
            message = await queue.get()
            if message is None:
                raise ConnectionClosedError("Server closed the connection")
            return message

        def _handle_connection_closed_by_server(self):
            self._game_message_queue.put_nowait(None)
            self._other_message_queue.put_nowait(None)
            self._other_message_queue = self._game_message_queue = None


@dataclass(frozen=True)
class ServerInfo:
    address: Address
