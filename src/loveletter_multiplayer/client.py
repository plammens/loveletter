import abc
import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Dict, Optional, Type, TypeVar

import valid8
from multimethod import multimethod

import loveletter_multiplayer.networkcomms.message as msg
from loveletter_multiplayer.exceptions import (
    ConnectionClosedError,
    InternalValidationError,
    LogonError,
    RemoteException,
    RemoteValidationError,
    RestartSession,
    UnexpectedMessageError,
)
from loveletter_multiplayer.networkcomms import (
    Message,
    MessageDeserializer,
    fill_placeholders,
    receive_message,
    send_message,
)
from loveletter_multiplayer.remotegame import RemoteGameShadowCopy
from loveletter_multiplayer.utils import (
    Address,
    InnerClassMeta,
    attrgetter,
    close_stream_at_exit,
)


LOGGER = logging.getLogger(__name__)


class LoveletterClient(metaclass=abc.ABCMeta):
    """
    Client end for a single player in a multiplayer Love Letter party.

    In order to play a multiplayer game, supposing each step goes smoothly,
    the caller must:

      1. Instantiate LoveletterClient
      2. Connect to the desired server (with :meth:`LoveletterClient.connect()`)
      3. If this client is the party host, send the ready message when all players have
         joined (with :meth:`HostClient.ready()`).
      4. Wait for the game to be created (with :meth:`LoveletterClient.wait_for_game()`)
      5. Play the game by starting :meth:`RemoteGameShadowCopy.track_remote` on
         :attr:`LoveletterClient.game` and handling the game events from then on.
      6. After the game has ended, if the client is the party host, send the shutdown
         message to the server (with :meth:`HostClient.send_shutdown()`).

    This is an abstract base class; the concrete classes are HostClient (for the party
    host) and GuestClient (for other clients).
    """

    username: str

    def __init__(self, username: str):
        self.username = username

        self._server_conn: Optional[LoveletterClient._ServerConnectionManager] = None
        self._connection_task: Optional[asyncio.Task] = None

    @property
    @abc.abstractmethod
    def is_host(self) -> bool:
        """Whether this client is the party host."""
        pass

    @property
    def game(self) -> Optional[RemoteGameShadowCopy]:
        return self._server_conn.game if self._server_conn is not None else None

    def __repr__(self):
        username, is_host = self.username, self.is_host
        return f"<{self.__class__.__name__} with {username=}, {is_host=}>"

    # -------------------------------- Public methods ---------------------------------

    # decorator for methods that need an active connection
    _needs_active_connection = valid8.validate_arg(
        "self",
        lambda self: self._server_conn is not None,
        lambda self: (t := self._connection_task) is not None and not t.done(),
        help_msg="No active connection",
    )

    async def connect(self, host, port) -> asyncio.Task:
        """
        Try connecting to a server and logging on.

        If this connection process fails at any point, the socket connection is closed
        and the exception is passed on to the caller. Otherwise, if it succeeds, a
        task is created (but not awaited) that handles the connection to the server
        while it lives, and it is returned to the caller.
        """
        reader, writer = await asyncio.open_connection(host=host, port=port)
        try:
            address = writer.get_extra_info("peername")
            LOGGER.info(f"Successfully connected to {address}")
            server_info = ServerInfo(address)
            # noinspection PyArgumentList
            manager = self._ServerConnectionManager(server_info, reader, writer)
            await manager.logon()
            task = asyncio.create_task(self._handle_connection(manager))
            # let the task initialize before returning
            # This idiom with asyncio.as_completed ensures that we never hang here
            # indefinitely: if the task completes first, it means that the manager
            # context was never entered and thus an exception was raised, so this will
            # re-raise; otherwise, the event was first meaning that the connection
            # attached successfully, so we can return.
            for aw in asyncio.as_completed([task, manager.attached_event.wait()]):
                await aw
                break
            return task
        except:  # noqa
            # we only close the stream if we weren't able to create the
            # _handle_connection task (e.g. something went wrong during logon,
            # or KeyboardInterrupt was raised); under normal circumstances,
            # the stream will be closed by the _handle_connection task
            writer.close()
            raise

    @_needs_active_connection
    async def wait_for_game(self) -> RemoteGameShadowCopy:
        """
        Wait for the remote game to be created.

        Must be called after the client has connected successfully. If this is being
        called by the host, it must be called after sending the ready to play message
        (with :meth:`ready`), otherwise a deadlock will ensue (the game can only be
        created after the host sends this message).

        If this succeeds, the caller can use :meth:`RemoteGameShadowCopy.track_remote()`
        on the returned game object (which will be the same object as :attr:`game`) to
        start playing the game.

        :returns: The created game.
        """
        return await self._server_conn.wait_for_game()

    # ------------------------------ Connection handling ------------------------------

    async def _handle_connection(
        self, manager: "LoveletterClient._ServerConnectionManager"
    ):
        async with close_stream_at_exit(manager.writer):
            if self._connection_task is not None:
                raise RuntimeError("_handle_connection already called")
            self._connection_task = asyncio.current_task()

            with manager as conn:
                try:
                    await conn.manage()
                except Exception as exc:
                    LOGGER.error("Unhandled exception in %s", conn, exc_info=exc)
                    # the client does raise; indeed the caller can retry connecting
                    raise

    class _ServerConnectionManager(metaclass=InnerClassMeta):
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

        # ------------------------------ Initialization -------------------------------

        def __init__(
            self, client: "LoveletterClient", server_info: "ServerInfo", reader, writer
        ):
            """
            Initialise a new server connection manager.

            Needs an active asyncio event loop (the same in which all other coroutines
            will be called) to be initialised properly.
            """
            self.client: LoveletterClient = client
            self.server_info = server_info
            self.reader: asyncio.StreamReader = reader
            self.writer: asyncio.StreamWriter = writer
            self._reset_game_vars()

            self._logged_on: bool = False
            self._receive_loop_active: bool = False

            self.attached_event = asyncio.Event()
            self._wait_for_game_started = asyncio.Event()
            self._manage_task: Optional[asyncio.Task] = None
            self._wait_for_game_task: Optional[asyncio.Task] = None
            self._queue_waiters: Dict[asyncio.Queue, asyncio.Task] = {}
            self._game_message_queue = asyncio.Queue()
            self._other_message_queue = asyncio.Queue()

        def _reset_game_vars(self):
            self.game = None
            self._deserializer = MessageDeserializer()
            try:
                self._wait_for_game_started.clear()
            except AttributeError:
                pass

        # ---------------------- Properties and special methods -----------------------

        @property
        def receiving(self) -> bool:
            return self._receive_loop_active

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
            self.attached_event.set()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.client._server_conn = None
            self.attached_event.clear()
            LOGGER.info("Deactivated %s", self)

        # ---------- "Public" methods (for Client and RemoteGameShadowCopy) -----------

        requires_logon = valid8.validate_arg(
            "self",
            attrgetter("_logged_on"),
            error_type=InternalValidationError,
            help_msg="The client needs to have logged on to the server",
        )

        requires_attached = valid8.validate_arg(
            "self",
            attrgetter("attached"),
            error_type=InternalValidationError,
            help_msg="This connection is not attached to the client",
        )

        async def logon(self):
            """
            Identify oneself to the server.

            Must be called after connecting to the server and before entering
            :meth:`manage`. Raises :class:`LogonError` if the logon fails.
            """
            message = msg.Logon(self.client.username)
            response = await self.request(message)
            if not isinstance(response, msg.OkMessage):
                if isinstance(response, msg.ErrorMessage):
                    raise LogonError(response.message)
                else:
                    # not an OK but not an error message either
                    raise UnexpectedMessageError(response)
            self._logged_on = True

        @requires_logon
        @requires_attached
        async def manage(self):
            """
            Manage the communication between client and server in this connection.

            Blocks until the server closes the connection, the task is cancelled or
            the task is otherwise killed by an exception.
            """
            # TODO: extract "call once" decorator
            if self._manage_task is not None:
                raise RuntimeError("manage has already been called")
            self._manage_task = task = asyncio.current_task()
            task.set_name(f"client<{self.client.username}>")
            while True:
                try:
                    while True:
                        try:
                            await asyncio.create_task(self._wait_for_game())
                            break
                        except RemoteException as e:
                            LOGGER.error(
                                "Remote exception while waiting for game; retrying",
                                exc_info=e,
                            )
                            self._wait_for_game_started.clear()

                    await self._receive_loop()
                    return
                except RestartSession:
                    LOGGER.info("Restarting session")
                    self._reset_game_vars()
                    continue

        @requires_attached
        async def wait_for_game(self) -> RemoteGameShadowCopy:
            """Called from outside the manage task to wait for the remote game."""
            # the first await is needed to ensure `self._wait_for_game_task` is not None
            await self._wait_for_game_started.wait()
            await self._wait_for_game_task
            return self.game

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
            await self.send_message(message)
            receiver = (
                self._get_message_from_queue(self._other_message_queue)
                if self._receive_loop_active
                else None
            )
            if message_type is None:
                request_to_response = {msg.ReadRequest: msg.DataMessage}
                # noinspection PyTypeChecker
                message_type = request_to_response.get(type(message), None)
            response = await self.expect_message(
                timeout=5.0, receiver=receiver, message_type=message_type
            )
            return response

        async def expect_message(
            self,
            timeout: Optional[float] = None,
            message_type: Optional[M] = None,
            receiver: Optional[Awaitable[Message]] = None,
        ) -> M:
            """
            Wait for an expected message from the server.

            Raises a ConnectionClosedError if the server closes the connection without
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

        del M
        GM = TypeVar("GM", bound=msg.GameMessage)

        async def get_game_message(self, message_type: Optional[Type[GM]] = None) -> GM:
            """
            Receive a game message.

            :param message_type: Expected game message (sub-)type, if any.
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

        del GM

        async def send_message(self, message: Message) -> None:
            """Low-level method to send a message to the server."""
            await send_message(self.writer, message)

        # ------------------------------ Session stages -------------------------------

        async def _wait_for_game(self):
            """Wait for the server to create the game."""
            self._wait_for_game_task = asyncio.current_task()
            self._wait_for_game_started.set()
            LOGGER.info("Waiting for remote game")
            self.game = await RemoteGameShadowCopy.from_connection(self)
            self._deserializer = MessageDeserializer(
                game=self.game, fill_placeholders=False
            )

        # ------------------------------- Receive loop --------------------------------

        async def _receive_loop(self):
            self._receive_loop_active = True
            LOGGER.debug("Started receive loop")
            try:
                while True:
                    message = await self._receive_message()
                    if not message:
                        break
                    LOGGER.debug("Received a message from the server: %s", message)
                    # noinspection PyTypeChecker
                    self._maybe_raise(message)
                    asyncio.create_task(
                        self._handle_message(message), name="handle_message"
                    )
            except ConnectionResetError:
                LOGGER.critical("Server forcefully closed the connection")
                raise
            else:
                LOGGER.info("Server closed the connection")
            finally:
                self._receive_loop_active = False
                self._game_message_queue.put_nowait(None)
                self._other_message_queue.put_nowait(None)
                self._other_message_queue = self._game_message_queue = None

        @multimethod
        async def _handle_message(self, message):
            await self._other_message_queue.put(message)
            LOGGER.debug("Put in other message queue: %s", message)

        @_handle_message.register
        async def _handle_message(self, message: msg.ErrorMessage):
            LOGGER.error("Error message from server: %s", message)
            self._maybe_raise(message)

        @_handle_message.register
        async def _handle_message(self, message: msg.GameMessage):
            await self._game_message_queue.put(message)
            LOGGER.debug("Put in game message queue: %s", message)

        # ------------------------------ Utility methods ------------------------------

        async def _receive_message(self) -> Message:
            """Receive a message from the server."""
            return await receive_message(self.reader, deserializer=self._deserializer)

        @staticmethod
        def _maybe_raise(message: Message):
            if isinstance(message, msg.ErrorMessage):
                if message.error_code == msg.ErrorMessage.Code.RESTART_SESSION:
                    LOGGER.error(
                        "Received signal to restart session: %s", message.message
                    )
                    raise RestartSession(message.message)
                elif isinstance(message, msg.ValidationErrorMessage):
                    raise RemoteValidationError(
                        message.exc_type, message.exc_message, message.help_message
                    )
                elif isinstance(message, msg.ExceptionMessage):
                    raise RemoteException(message.exc_type, message.exc_message)

        async def _get_message_from_queue(self, queue: asyncio.Queue) -> Message:
            """Get a message from a queue, ensuring the connection is still open."""
            if not self.receiving or queue is None:
                raise ConnectionClosedError("Receiver is no longer active")
            if queue in self._queue_waiters:
                raise RuntimeError("There is already another task waiting on a message")
            self._queue_waiters[queue] = asyncio.current_task()
            try:
                message = await queue.get()
                if message is None:
                    raise ConnectionClosedError("Server closed the connection")
                return message
            finally:
                del self._queue_waiters[queue]


class HostClient(LoveletterClient):
    @property
    def is_host(self) -> bool:
        return True

    @LoveletterClient._needs_active_connection
    async def ready(self):
        """
        Send a message to the server indicating that this client is ready to play.

        Must be called after :meth:`connect` returned successfully.
        """
        await self._server_conn.send_message(msg.ReadyToPlay())

    @LoveletterClient._needs_active_connection
    async def send_shutdown(self):
        """Send a shutdown message to the server."""
        LOGGER.info("Sending shutdown message to server")
        await self._server_conn.send_message(msg.Shutdown())
        await self._connection_task  # wait for the connection to shut down


class GuestClient(LoveletterClient):
    @property
    def is_host(self) -> bool:
        return False


@dataclass(frozen=True)
class ServerInfo:
    address: Address


def watch_connection(connection: asyncio.Task) -> asyncio.Task:
    """
    Utility to watch a client connection and propagate exceptions that occur.

    Called from a coroutine that manages a :class:`LoveletterClient` on the result of
    :meth:`LoveletterClient.connect()` to set up a watcher task that, when the
    connection terminates due to an exception, throws said exception back into the
    caller coroutine using :meth:`coroutine.throw()`.

    :param connection: Connection task (as returned by ``.connect()``) to watch.
    :returns: The newly created watcher task.
    """
    caller = asyncio.current_task().get_coro()

    async def watcher():
        try:
            await connection
        except Exception as e:
            LOGGER.debug("Watcher is throwing %s into %s", e, caller)
            caller.throw(e)

    return asyncio.create_task(watcher())
