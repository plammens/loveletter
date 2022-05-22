import abc
import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Coroutine, Dict, Optional, Type, TypeVar, Union

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
    cancel_and_await,
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
        and the exception is propagated to the caller.
        Otherwise, if it succeeds, a connection task is created.
        This task handles the connection to the server: in particular,
        it listens for incoming messages and other signals from the server,
        for example when the server closes the connection
        (see :meth:`LoveletterClient._ServerConnectionManager.manage`).

        :raises ConnectionError: if the connection fails at the socket level.
        :raises LogonError: if logon fails.

        :return: The connection task described above.
        """
        reader, writer = await asyncio.open_connection(host=host, port=port)
        try:
            address = writer.get_extra_info("peername")
            LOGGER.debug(f"Successfully connected to server address %s", address)
            server_info = ServerInfo(address)
            # noinspection PyArgumentList
            manager = self._ServerConnectionManager(server_info, reader, writer)
            await manager.logon()
            connection_task = asyncio.create_task(
                self._handle_connection(manager), name=f"server_connection"
            )
            # let the task initialize before returning
            # this usage of asyncio.wait() lets us wait until either the connection
            # task terminates prematurely (due to an error) or the connection
            # is activated successfully
            await asyncio.wait(
                [connection_task, manager.attached_event.wait()],
                return_when=asyncio.FIRST_COMPLETED,
            )
            return connection_task
        except:
            # we only close the stream if we weren't able to create the
            # _handle_connection task (e.g. something went wrong during logon,
            # or KeyboardInterrupt was raised); under normal circumstances,
            # the stream will be closed by the _handle_connection task
            writer.close()
            await writer.wait_closed()
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
        """
        A small wrapper around ``manager.manage()``.

        It "attaches" the connection to the client and then delegates to the manager.
        This method checks that it's only been called once per connection.

        :param manager: Server connection manager whose connection is to be handled.
        """
        if self._connection_task is not None:
            raise RuntimeError("_handle_connection already called")
        self._connection_task = asyncio.current_task()

        async with manager:
            await manager.manage()

    class _ServerConnectionManager(metaclass=InnerClassMeta):
        """
        Manages the connection with the server.

        When used as a context manager, entering the context represents attaching this
        connection to the client, and exiting it represents detaching it and closing the
        underlying socket.

        A session can only start being managed if it has been successfully been set as the
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
            self._started_waiting_for_game = asyncio.Event()
            self._manage_task: Optional[asyncio.Task] = None
            self._wait_for_game_task: Optional[asyncio.Task] = None
            self._queue_waiters: Dict[asyncio.Queue, asyncio.Task] = {}
            self._game_message_queue = asyncio.Queue()
            self._other_message_queue = asyncio.Queue()

        def _reset_game_vars(self):
            self.game = None
            self._deserializer = MessageDeserializer()
            try:
                self._started_waiting_for_game.clear()
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

        async def __aenter__(self):
            LOGGER.info("Activating %s", self)
            if self.client._server_conn is not None:
                raise RuntimeError("There is already an active connection")
            self.client._server_conn = self
            self.attached_event.set()
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            if exc_type is not None:
                LOGGER.error(
                    "Unhandled exception in %s",
                    self,
                    exc_info=(exc_type, exc_val, exc_tb),
                )

            self.writer.close()
            self.client._server_conn = None
            self.attached_event.clear()
            await self.writer.wait_closed()
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
            :meth:`manage`.

            :raises LogonError: if the logon fails.
            """
            message = msg.Logon(self.client.username)
            response = await self.request(message)
            if not isinstance(response, msg.OkMessage):
                if isinstance(response, msg.ErrorMessage):
                    raise LogonError(response.message)
                else:
                    # not an OK but not an error message either
                    raise UnexpectedMessageError(
                        expected=msg.OkMessage, actual=response
                    )
            self._logged_on = True
            LOGGER.info(f"Logged on successfully to server: %s", self.server_info)

        @requires_logon
        @requires_attached
        async def manage(self):
            """
            Manage the communication between client and server in this connection.

            Should only be called after the client has successfully logged on and
            the connection has been activated.

            Blocks until the server closes the connection, the task is cancelled or
            the task is otherwise killed by an exception.
            """
            # TODO: extract "call once" decorator
            if self._manage_task is not None:
                raise RuntimeError("manage has already been called")
            self._manage_task = task = asyncio.current_task()
            task.set_name(f"client<{self.client.username}>")

            while True:
                # one complete session
                try:
                    # wait for game
                    while True:
                        try:
                            await asyncio.create_task(self._wait_for_game())
                            break
                        except RemoteException as e:
                            LOGGER.error(
                                "Remote exception while waiting for game; retrying",
                                exc_info=e,
                            )
                            continue

                    # after game has started, just handle incoming messages
                    await self._receive_loop()
                    return
                except RestartSession:
                    LOGGER.info("Restarting session")
                    self._reset_game_vars()
                    continue

        @requires_attached
        async def wait_for_game(self) -> RemoteGameShadowCopy:
            """Called from outside the manage task to wait for the remote game."""
            # The first await ensures ``self._wait_for_game_task`` is not None.
            # The reason to use this event and then wait for the task instead of e.g.
            # making a single event for when the game has been created is to be able to
            # easily propagate exceptions that originate in the _wait_for_game_task.
            await self._started_waiting_for_game.wait()
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
            message_type: Optional[Type[M]] = None,
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
                raise UnexpectedMessageError(expected=message_type, actual=message)
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
                raise UnexpectedMessageError(expected=message_type, actual=message)
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
            self._started_waiting_for_game.set()
            try:
                LOGGER.info("Waiting for remote game")
                message = await self._wait_for_game_created_message()
                LOGGER.info("Remote game created; creating local copy")
                self.game = RemoteGameShadowCopy.from_message(self, message)
                self._deserializer = MessageDeserializer(
                    game=self.game, fill_placeholders=False
                )
            except:
                self._started_waiting_for_game.clear()
                raise

        async def _wait_for_game_created_message(self) -> msg.GameCreated:
            """Handle messages until the GameCreated message, and return that."""
            return await self.expect_message(message_type=msg.GameCreated)

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
                    await self._handle_message(message)
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
    def __init__(
        self,
        username: str,
        player_joined_callback: Callable[[msg.PlayerJoined], Awaitable] = None,
    ):
        """
        :param username: Player username.
        :param player_joined_callback: Called and awaited when a new player
            joins the game (logs on to the server).
        """
        super().__init__(username)

        async def noop_callback(message):
            pass

        self.player_joined_callback = player_joined_callback or noop_callback

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

    class _ServerConnectionManager(LoveletterClient._ServerConnectionManager):
        async def _wait_for_game_created_message(self) -> msg.GameCreated:
            while True:
                message = await self.expect_message()
                if isinstance(message, msg.PlayerJoined):
                    # noinspection PyTypeChecker
                    client: HostClient = self.client
                    await client.player_joined_callback(message)
                elif isinstance(message, msg.GameCreated):
                    break
                else:
                    raise UnexpectedMessageError(
                        expected=msg.GameCreated, actual=message
                    )

            return message


class GuestClient(LoveletterClient):
    @property
    def is_host(self) -> bool:
        return False


@dataclass(frozen=True)
class ServerInfo:
    address: Address


async def watch_connection(
    connection_task: asyncio.Task, main_task: Union[asyncio.Task, Coroutine]
):
    """
    Utility to watch a client connection while running some other main task.

    Called from a coroutine that manages a :class:`LoveletterClient` on the result of
    :meth:`LoveletterClient.connect` to set up a task that does something while
    "keeping an eye" on the connection: i.e. if the connection terminates with an
    exception, it stops the main task and propagates said exception to the caller.
    If no exception occurs, waits for both tasks to terminate normally.

    :param connection_task: Connection task to watch, as returned by
        :meth:`LoveletterClient.connect`.
    :param main_task: Main task to run while watching the connection task.
        Can be given as a coroutine object, in which case it will be wrapped
        in a task with the same name as the current task.
    """
    if asyncio.iscoroutine(main_task):
        main_task = asyncio.create_task(
            main_task, name=asyncio.current_task().get_name()
        )

    done, pending = await asyncio.wait(
        [connection_task, main_task], return_when=asyncio.FIRST_EXCEPTION
    )
    # if stopped early due to an exception, cancel the main task
    await cancel_and_await(*pending)
    # propagate the exception (if any)
    for task in done:
        task.result()  # this raises if the task terminated with an exception
