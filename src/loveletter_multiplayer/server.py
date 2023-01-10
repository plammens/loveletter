import asyncio
import dataclasses
import itertools
import logging
import socket
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple, Union

import more_itertools as mitt
import valid8
from multimethod import multimethod

import loveletter.game
import loveletter.gameevent as gev
import loveletter.gamenode as gnd
import loveletter.move as move
import loveletter.round as rnd
import loveletter_multiplayer.networkcomms.message as msg
from loveletter_multiplayer.exceptions import (
    ConnectionClosedError,
    LogonError,
    ProtocolError,
    RestartSession,
    UnexpectedMessageError,
)
from loveletter_multiplayer.networkcomms import (
    Message,
    MessageDeserializer,
    MessageSerializer,
    receive_message,
    send_message,
)
from loveletter_multiplayer.utils import (
    Address,
    InnerClassMeta,
    close_stream_at_exit,
    format_exception,
    import_from_qualname,
    watch_task,
)


LOGGER = logging.getLogger(__name__)


class LoveletterPartyServer:
    """
    A server for a party of Love Letter.

    A party is a group of physical players that is going to play a game together.

    The maximum number of clients this can serve is the maximum amount of players
    allowed in a game. After this number is reached, any further connections will be
    sent an error message and will be subsequently closed.
    """

    host: Union[str, Tuple[str, ...]]
    port: int
    game: Optional[loveletter.game.Game]

    # -------------------------------- Initialization ---------------------------------

    def __init__(
        self,
        host,
        port,
        *,
        party_host_username: str,
        max_clients: int = loveletter.game.Game.MAX_PLAYERS,
        allow_duplicate_usernames: bool = False,
        host_join_timeout: Optional[float] = None,
    ):
        """
        Initialize a new server instance.

        :param host: Host IP/name to bind the server to, or a sequence of such items.
        :param port: Port number to bind the server to.
        :param party_host_username: The username of the player that will host this party
                                    (has additional privileges to configure the party).
        :param max_clients: Maximum number of clients allowed to log onto the server.
        :param allow_duplicate_usernames: Whether clients are allowed to connect if
            their username is already taken by another client connected to the server.
        :param host_join_timeout: How long to wait for the host to join when the server
            starts up, in seconds. ``None`` indicates no timeout.
        """
        self.host = host[0] if not isinstance(host, str) and len(host) == 1 else host
        self.port = port

        self.max_clients = max_clients
        self.allow_duplicate_usernames = allow_duplicate_usernames
        self.host_join_timeout = host_join_timeout

        self._client_sessions: List[LoveletterPartyServer._ClientSessionManager] = []
        self._party_host_username = party_host_username

        self._serializer = MessageSerializer()
        self._deserializer = MessageDeserializer()

        self._reset_game_vars()

        # to be initialized in self._init_async:
        self._server: asyncio.AbstractServer
        self._sessions_lock: asyncio.Lock
        self._ready_to_play: asyncio.Event
        self._connection_server_task: Optional[asyncio.Task] = None
        self._playing_game_task: Optional[asyncio.Task] = None

    def _reset_game_vars(self):
        self.game = None
        self._playing_game_task = None
        self._deserializer = MessageDeserializer()
        self._game_input_request_id_gen: Iterator[int] = itertools.count(0)
        try:
            self._ready_to_play.clear()
        except AttributeError:
            pass

    async def _init_async(self):
        """Initialize asyncio-related attributes that need an active event loop."""
        LOGGER.debug("Initializing async variables")
        self._server = await asyncio.start_server(
            client_connected_cb=self._connection_handler,
            host=self.host,
            port=self.port,
            backlog=self.max_clients + 5,  # allow some space to handle excess connects
            start_serving=False,
        )
        LOGGER.debug(f"Created socket server bound to {self.host}:{self.port}")
        self._sessions_lock = asyncio.Lock()
        self._ready_to_play = asyncio.Event()
        self._host_joined = asyncio.Event()

    # ------------------------- Properties and public methods -------------------------

    @property
    def num_connected_clients(self) -> int:
        """The number of clients currently being served by the server."""
        return len(self._client_sessions)

    @property
    def party_host(self) -> Optional["ClientInfo"]:
        """Get the ClientInfo corresponding to the host of this party, if present."""
        return mitt.only(
            client
            for session in self._client_sessions
            if (client := session.client_info).is_host
        )

    @property
    def party_host_session(
        self,
    ) -> Optional["LoveletterPartyServer._ClientSessionManager"]:
        client = self.party_host
        return self._client_sessions[client.id] if client is not None else None

    @property
    def game_in_progress(self):
        """Whether a game has been created and is currently in progress."""
        return (
            self._ready_to_play.is_set()
            and self.game is not None
            and self._playing_game_task is not None
            and not self._playing_game_task.done()
        )

    @property
    def game_ended(self):
        """Whether a game has been created and has been fully played through."""
        return (
            self._ready_to_play.is_set()
            and self.game is not None
            and self.game.ended
            and self._playing_game_task is not None
            and self._playing_game_task.done()
        )

    async def run_server(self):
        """
        Starts the connection server and lasts until the server shuts down.

        Can only be called once per instance.

        :raises asyncio.TimeoutError: if waiting for the host to join times out.
        """
        if self._connection_server_task is not None:
            raise RuntimeError("run_server can only be called once")
        self._connection_server_task = asyncio.current_task()
        await self._init_async()
        async with self._server:
            game_task = asyncio.create_task(
                self._start_game_when_ready(), name="start_game_when_ready"
            )
            try:
                LOGGER.info("Starting socket server")
                await watch_task(game_task, main_task=self._server.serve_forever())
            except asyncio.CancelledError:
                pass  # exiting gracefully
            finally:
                LOGGER.info("Server shutting down")
                self._connection_server_task = None

    # ---------------------------- Info/definition methods ----------------------------

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

    # ------------------------ Connection and session handling ------------------------

    async def _connection_handler(
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
            task.set_name(f"connection<{address}>")

            # hold the lock until we attach the session (or refuse the connection)
            async with self._sessions_lock:
                # Note: if we refuse the connection now, there is no need to wait for
                # the logon message since we would have rejected in any case.

                if self.num_connected_clients >= self.max_clients:
                    return await self._refuse_connection(
                        writer,
                        reason=f"Maximum capacity ({self.max_clients} players) reached",
                    )

                if self._ready_to_play.is_set():
                    return await self._refuse_connection(
                        writer,
                        reason="A game is already in progress",
                    )

                LOGGER.info(f"Received connection from %s", address)
                try:
                    client_info = await self._receive_logon(reader, writer)
                except (LogonError, ProtocolError, asyncio.TimeoutError) as e:
                    await self._refuse_connection(writer, reason=str(e))
                    return

                # noinspection PyArgumentList
                session = self._ClientSessionManager(client_info, reader, writer)
                # attach before releasing the lock:
                self._attach(session)

            async with session:
                try:
                    # where the actual session is managed; this suspends this
                    # coroutine until the session ends in some way
                    await session.manage()
                except Exception as exc:
                    LOGGER.critical(
                        "Unhandled exception in client handler", exc_info=exc
                    )
                    # suppress exception so server keeps running

    async def _refuse_connection(
        self,
        writer,
        *,
        reason: str,
        error_code: msg.ErrorMessage.Code = msg.ErrorMessage.Code.CONNECTION_REFUSED,
    ):
        address = writer.get_extra_info("peername")
        LOGGER.info(f"Refusing connection from %s (%s)", address, reason)
        await self._reply_error(writer, error_code, reason)
        writer.write_eof()

    async def _receive_logon(self, reader, writer) -> "ClientInfo":
        """
        Receive the logon info from the given peer and validate it.

        If the logon succeeds, this also sends an OK reply to the peer that sent it.

        :param reader: StreamReader corresponding to the new connection.
        :param writer: StreamWriter corresponding to the new connection.

        :return: The client info of the newly connected player if logon was successful.
        :raises asyncio.TimeoutError: If the logon message doesn't arrive after a while.
        :raises ProtocolError: If the peer doesn't abide by the logon protocol.
        :raises LogonError: If the logon is invalid for some logical reason
            (e.g. duplicate username).
        """
        address = Address(*writer.get_extra_info("peername"))

        try:
            # need a timeout because we're holding a lock that is blocking other conns.
            message = await asyncio.wait_for(self._receive_message(reader), timeout=3.0)
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
            raise UnexpectedMessageError(expected=msg.Logon, actual=message)

        # check for duplicate username
        if not self.allow_duplicate_usernames and message.username in (
            c.client_info.username for c in self._client_sessions
        ):
            raise LogonError(f"Username already in use: {message.username!r}")

        client_info = ClientInfo(
            address=address,
            id=len(self._client_sessions),
            username=message.username,
        )
        if self._is_host(client_info):
            client_info = dataclasses.replace(client_info, is_host=True)
        else:
            # Check that the host is present when guests arrive.
            if self.party_host is None:
                raise LogonError("This server's host hasn't connected yet.")

        await self._reply_ok(writer)
        return client_info

    def _attach(self, session: "LoveletterPartyServer._ClientSessionManager"):
        # this context manager is not async so no need to lock read/write accesses
        LOGGER.info("Starting session for %s", session.client_info)
        address = session.client_info.address
        if address in (s.client_info.address for s in self._client_sessions):
            raise RuntimeError("There is already a session for %s", address)

        object.__setattr__(session.client_info, "id", len(self._client_sessions))
        self._client_sessions.append(session)
        session._attached = True

        if session.client_info.is_host:
            self._host_joined.set()

        return session

    def _detach(self, session: "LoveletterPartyServer._ClientSessionManager"):
        address = session.client_info.address
        if session not in self._client_sessions:
            raise RuntimeError(
                "Trying to detach an already detached connection %s", address
            )
        self._client_sessions.remove(session)
        session._attached = False
        LOGGER.info(f"Session with %s has ended", session.client_info)

    class _ClientSessionManager(metaclass=InnerClassMeta):
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
            self.session_task: Optional[asyncio.Task] = None

            self._attached = False
            self._receive_loop_task = None
            self._game_message_queue = asyncio.Queue()

        @property
        def receiving(self):
            return (
                self._receive_loop_task is not None
                and not self._receive_loop_task.done()
            )

        def __repr__(self):
            return f"<session manager for {self.client_info}>"

        async def __aenter__(self):
            """Attach this session to the server."""
            async with self.server._sessions_lock:
                if self not in self.server._client_sessions:
                    self.server._attach(self)

            await self.server._announce_new_player(self)

            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            """Detach this session from the server, make sure the socket is closed."""
            self.writer.close()
            await self.writer.wait_closed()

            async with self.server._sessions_lock:
                self.server._detach(self)

            # if waiting for the game to start, announce the disconnection politely
            if not self.server._ready_to_play.is_set():
                await self.server._announce_player_disconnected(self)

        # --------------------- "Public" methods (for the server) ---------------------

        async def manage(self):
            """
            Manage this client session.

            Can only be called if this session has been attached to the server (i.e.
            it can only be called inside a `with self` block).
            """
            if not self._attached:
                raise RuntimeError("Cannot manage a detached session")
            if self.session_task is not None:
                raise RuntimeError(".manage() already called")
            self.session_task = task = asyncio.current_task()
            task.set_name(f"connection<{self.client_info.username}>")
            recv_loop = asyncio.create_task(self._receive_loop(), name="receive_loop")
            while True:
                try:
                    await recv_loop
                    return
                except RestartSession as exc:
                    await self.reply_error(
                        msg.ErrorMessage.Code.RESTART_SESSION, str(exc)
                    )
                    continue

        async def end(self):
            """
            Gracefully end this session.

            This involves:
              - Closing the underlying socket, writing EOF first if possible.
              - Cancelling any long-term tasks related to this session,
                such as the receive loop.

            When the manage() task (started in _connection_handler) is cancelled,
            due to the context manager use the session will also be
            automatically detached from the server.
            """
            LOGGER.debug("Ending session for: %s", self.client_info)
            current_task = asyncio.current_task()

            try:
                self.writer.write_eof()
                await self.writer.drain()
            except OSError:
                # The connection might have already been closed by the other end.
                pass
            self.writer.close()

            tasks = [self.writer.wait_closed()]
            for task in self._receive_loop_task, self.session_task:
                if task is current_task:
                    raise RuntimeError(f"Can't cancel from within {task}")
                task.cancel()
                tasks.append(task)

            await asyncio.gather(*tasks, return_exceptions=True)

        async def abort(self):
            """Abort this session."""
            LOGGER.warning("Aborting session with %s", self.client_info)
            await self.end()

        @multimethod
        async def game_input_request(self, request: gev.ChoiceEvent) -> gev.ChoiceEvent:
            """Make a GameInputRequest to the client and wait for the response."""
            LOGGER.info(
                "Making game input request to %s: %s", self.client_info, request
            )
            request_id = next(self.server._game_input_request_id_gen)
            request_message = msg.GameInputRequestMessage(request, id=request_id)
            await send_message(self.writer, request_message)
            response = await self._receive_game_choice()
            assert import_from_qualname(response.choice_class) is type(request)
            request.set_from_serializable(response.choice)
            LOGGER.info("Client responded: %s", request)
            await self._relay_response(response)  # broadcast response to other players
            return request

        async def send_message(self, message: Message):
            await self.server._send_message(self.writer, message)

        async def reply_ok(self):
            await self.server._reply_ok(self.writer)

        async def reply_error(self, code, reason):
            await self.server._reply_error(self.writer, code, reason)

        async def reply_exception(self, message: str, exception: Exception):
            if isinstance(exception, valid8.ValidationError):
                message = msg.ValidationErrorMessage(
                    message,
                    exc_type=type(exception),
                    exc_message=str(exception),
                    help_message=exception.get_help_msg(),
                )
            else:
                message = msg.ExceptionMessage(message, type(exception), str(exception))
            await self.send_message(message)

        # --------------------------- Receive loop methods ----------------------------

        async def _receive_loop(self):
            if self._receive_loop_task is not None:
                raise RuntimeError("_receive_loop already called")
            self._receive_loop_task = asyncio.current_task()
            try:
                while True:
                    message = await self._receive_message()
                    if not message:
                        break
                    LOGGER.debug(
                        "Received a message from %s: %s", self.client_info, message
                    )
                    asyncio.create_task(
                        self._handle_message(message), name="handle_message"
                    )
            except OSError:
                LOGGER.warning(
                    "Connection failed or forcibly closed by client: %s",
                    self.client_info,
                )
                asyncio.create_task(
                    self._connection_closed_by_client(),
                    name="connection_closed_handler",
                )
            else:
                LOGGER.info("Client closed the connection: %s", self.client_info)
                asyncio.create_task(
                    self._connection_closed_by_client(),
                    name="connection_closed_handler",
                )
            finally:
                self._game_message_queue.put_nowait(None)
                self._game_message_queue = None

        async def _receive_message(self) -> Message:
            return await self.server._receive_message(self.reader)

        @multimethod
        async def _handle_message(self, message: msg.Message):
            raise NotImplementedError

        @_handle_message.register
        async def _handle_message(self, message: msg.ErrorMessage):
            raise NotImplementedError

        # noinspection PyUnusedLocal
        @_handle_message.register
        async def _handle_message(self, message: msg.Logon):
            LOGGER.warning("Received duplicate logon from %s", self.client_info)
            await self.reply_error(
                msg.ErrorMessage.Code.LOGON_ERROR,
                "Can only log on to the party once",
            )

        # noinspection PyUnusedLocal
        @_handle_message.register
        async def _handle_message(self, message: msg.ReadyToPlay):
            if self.client_info.is_host:
                self.server._ready_to_play.set()
                # reply will be sent by _start_game_when_ready
            else:
                await self._reply_permission_denied(message)

        @_handle_message.register
        async def _handle_message(self, message: msg.ReadRequest):
            attrs = message.request.split(".")[::-1]
            try:
                obj = self.server
                while attrs:
                    obj = getattr(obj, attrs.pop())
            except AttributeError as e:
                await self.reply_error(
                    msg.ErrorMessage.Code.ATTRIBUTE_ERROR,
                    format_exception(e),
                )
                return

            message = msg.DataMessage(obj)
            LOGGER.debug("Responding to read request with %s", message)
            try:
                await self.send_message(message)
            except TypeError:
                await self.reply_error(
                    msg.ErrorMessage.Code.SERIALIZE_ERROR,
                    reason="Requested object can't be serialized",
                )
                return

        @_handle_message.register
        async def _handle_message(self, message: msg.FulfilledChoiceMessage):
            await self._game_message_queue.put(message)

        # noinspection PyUnusedLocal
        @_handle_message.register
        async def _handle_message(self, message: msg.Shutdown):
            if self.server.game_ended:
                if self.client_info.is_host:
                    return await self.server._shutdown()
                else:
                    LOGGER.warning(
                        "Ignoring shutdown message from non-host client %s",
                        self.client_info,
                    )
            else:
                LOGGER.warning("Ignoring shutdown message received before game ended")

        async def _connection_closed_by_client(self):
            """Callback for when the connection is closed/reset from the client side."""
            LOGGER.debug(f"Handling connection closed by client {self.client_info}")
            await self.abort()
            server = self.server
            if self.client_info.is_host:
                # host left; abort all sessions
                reason = "Host disconnected"
                await server._abort_server(reason)
            elif server._ready_to_play.is_set() and not server.game_ended:
                # a game was in progress;
                # for now just abort the game and restart all sessions
                server._abort_current_game(
                    f"Player {self.client_info.username} disconnected"
                )

        # ------------------------------ Utility methods ------------------------------

        async def _receive_game_choice(self) -> msg.FulfilledChoiceMessage:
            # noinspection PyTypeChecker
            message: msg.GameMessage = await self._get_message_from_queue(
                self._game_message_queue
            )
            if not isinstance(message, msg.FulfilledChoiceMessage):
                raise UnexpectedMessageError(
                    expected=msg.FulfilledChoiceMessage, actual=message
                )
            return message

        async def _get_message_from_queue(self, queue: asyncio.Queue) -> Message:
            """Get a message from a queue, ensuring the connection is still open."""
            if not self.receiving or queue is None:
                raise ConnectionClosedError("Receiver is no longer active")
            message = await queue.get()
            if message is None:
                raise ConnectionClosedError("Client closed the connection")
            return message

        async def _relay_response(self, response: msg.FulfilledChoiceMessage):
            """Broadcast a choice made by this client to all other clients."""
            LOGGER.debug("Relaying choice to other players: %s", response)
            sessions = set(self.server._client_sessions) - {self}
            tasks = (s.send_message(response) for s in sessions)
            await asyncio.gather(*tasks)

        async def _reply_permission_denied(self, cause):
            LOGGER.warning(
                "Received unauthorized request form %s: %s", self.client_info, cause
            )
            await self.reply_error(
                msg.ErrorMessage.Code.PERMISSION_DENIED,
                reason="Only the host can do this",
            )

    # ---------------------- Coroutines for managing each stage -----------------------

    async def _announce_new_player(self, new_player: _ClientSessionManager):
        await self.party_host_session.send_message(
            msg.PlayerJoined(new_player.client_info.username)
        )

    async def _announce_player_disconnected(self, player: _ClientSessionManager):
        # Can't announce anything to the host if the host themselves disconnected.
        if not player.client_info.is_host:
            await self.party_host_session.send_message(
                msg.PlayerDisconnected(player.client_info.username)
            )

    async def _start_game_when_ready(self):
        # Wait for the host to join, with a timeout (to avoid an orphan server process).
        try:
            await asyncio.wait_for(
                self._host_joined.wait(),
                timeout=self.host_join_timeout,
            )
        except asyncio.TimeoutError:
            LOGGER.error("Timed out while waiting for host to join")
            raise

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
                self.game = self._deserializer.game = self._create_game(usernames)
                break
            except Exception as e:
                LOGGER.warning("Exception while trying to create game", exc_info=e)
                self._ready_to_play.clear()
                await self.party_host_session.reply_exception(
                    f"Exception while trying to create game", exception=e
                )
                continue

        LOGGER.info("Ready to play; created game: %s", self.game)
        tasks = (
            s.send_message(
                msg.GameCreated(self.game.players, player_id=s.client_info.id)
            )
            for s in self._client_sessions
        )
        await asyncio.gather(*tasks)
        asyncio.create_task(self._play_game(), name="play_game")

    def _create_game(self, usernames: List[str]) -> loveletter.game.Game:
        """Subclasses can override this to customise game creation."""
        return loveletter.game.Game(usernames)

    async def _play_game(self):
        """This coroutine manages the central (server's) copy of the game."""

        if self._playing_game_task is not None:
            raise RuntimeError("_play_game already called")
        self._playing_game_task = asyncio.current_task()
        LOGGER.info("Starting game")

        @multimethod
        async def handle(e: gev.GameEvent) -> gev.GameEvent:
            raise NotImplementedError(e)

        @handle.register
        async def handle(e: None):
            return e

        # noinspection PyUnusedLocal
        @handle.register
        async def handle(e: gev.GameResultEvent):
            pass  # server doesn't need to do anything with this info

        @handle.register
        async def handle(e: gnd.GameNodeState):
            message = msg.GameNodeStateMessage(e)
            await asyncio.gather(
                *(s.send_message(message) for s in self._client_sessions)
            )

        @handle.register
        async def handle(e: loveletter.game.PlayingRound):
            # include deck so clients can sync
            message = msg.RoundInitMessage(e, deck=e.round.deck)
            await asyncio.gather(
                *(s.send_message(message) for s in self._client_sessions)
            )

        @handle.register
        async def handle(e: gev.GameInputRequest):
            raise NotImplementedError(e)

        @handle.register
        async def handle(e: gev.ChoiceEvent):
            # default: ask the host
            host_session = self.party_host_session
            e = await host_session.game_input_request(e)
            return e

        @handle.register
        async def handle(e: rnd.ChooseCardToPlay):
            player = self.game.current_round.current_player
            session = self._client_sessions[player.id]
            assert session.client_info.id == player.id
            e = await session.game_input_request(e)
            return e

        @handle.register
        def handle(e: move.MoveStep):
            # reuse code from ChooseCardToPlay handler
            # fmt:off
            return handle[rnd.ChooseCardToPlay,](e)
            # fmt:on

        try:
            game = self.game
            game_generator = game.play()
            event = None
            while True:
                try:
                    # noinspection PyTypeChecker
                    event = game_generator.send(await handle(event))
                except StopIteration as end:
                    (game_end,) = end.value
                    break
                LOGGER.info("Server game generated event: %s", event)

            LOGGER.info("Game has ended: %s", event)
            end_message = msg.GameEndMessage(game_end)
            await asyncio.gather(
                *(s.send_message(end_message) for s in self._client_sessions)
            )
        except Exception as e:
            LOGGER.critical("Unhandled exception while playing game", exc_info=e)
        finally:
            LOGGER.debug("_play_game has finished")

    # ---------------------------- Shutdown/abort methods -----------------------------

    def _abort_current_game(self, reason: str):
        if self.game_ended:
            raise RuntimeError("Game has already ended")
        LOGGER.warning(
            f"Aborting game and restarting remaining sessions "
            f"({len(self._client_sessions)})"
        )
        self._playing_game_task.cancel("Aborting current game and restarting")
        exc = RestartSession(reason)
        for session in self._client_sessions:
            coro = session.session_task.get_coro()
            coro.throw(exc)
        self._reset_game_vars()
        asyncio.create_task(
            self._start_game_when_ready(), name="_start_game_when_ready"
        )

    async def _abort_server(self, reason: str):
        LOGGER.critical("Aborting server: %s", reason)

        async def abort(session):
            await session.reply_error(msg.ErrorMessage.Code.SESSION_ABORTED, reason)
            await session.abort()

        await asyncio.gather(*(abort(s) for s in self._client_sessions))
        self._connection_server_task.cancel()

    async def _shutdown(self):
        """Gracefully shut down the server after having finished a game."""
        LOGGER.debug("Server's _shutdown called")
        if not self.game_ended:
            raise RuntimeError("Game hasn't been finished yet")
        await asyncio.gather(*(s.end() for s in self._client_sessions))
        self._connection_server_task.cancel()

    # -------------------------------- Utility methods --------------------------------

    async def _send_message(self, writer: asyncio.StreamWriter, message: Message):
        await send_message(writer, message, serializer=self._serializer)

    async def _receive_message(self, reader: asyncio.StreamReader) -> Message:
        return await receive_message(reader, deserializer=self._deserializer)

    async def _reply_ok(self, writer):
        message = msg.OkMessage()
        await self._send_message(writer, message)

    async def _reply_error(self, writer, code, reason):
        address = writer.get_extra_info("peername")
        message = msg.ErrorMessage(code, reason)
        LOGGER.debug("Sending error response to %s: %s", address, message)
        await self._send_message(writer, message)


@dataclass(frozen=True)
class ClientInfo:
    address: Address
    id: Optional[int]
    username: Optional[str]
    is_host: bool = False  # host of the party; has privileges to configure the server
