import abc
import asyncio
import enum
import logging
import random
import sys
from dataclasses import dataclass, field
from typing import Optional, Tuple

import more_itertools as mitt
import valid8
from aioconsole import ainput, aprint
from multimethod import multimethod

import loveletter.game
import loveletter.gameevent as gev
import loveletter.move as mv
import loveletter.round as rnd
import loveletter_multiplayer.networkcomms.message as msg
from loveletter.cards import CardType
from loveletter_cli.data import MoveChoice, UserInfo
from loveletter_cli.exceptions import Restart
from loveletter_cli.server_process import ServerProcess
from loveletter_cli.ui import (
    async_ask_valid_input,
    draw_game,
    pause,
    pluralize,
    print_centered,
    print_exception,
    print_header,
)
from loveletter_cli.utils import camel_to_phrase
from loveletter_multiplayer import (
    GuestClient,
    HostClient,
    LogonError,
    RemoteEvent,
    RemoteException,
    RemoteGameShadowCopy,
    RemoteValidationError,
)
from loveletter_multiplayer.client import LoveletterClient
from loveletter_multiplayer.utils import Address, watch_task


LOGGER = logging.getLogger(__name__)


@dataclass
class CommandLineSession(metaclass=abc.ABCMeta):
    """CLI session manager."""

    user: UserInfo
    client: LoveletterClient = field(init=False)

    @abc.abstractmethod
    async def manage(self):
        """Main entry point to run and manage this session."""
        asyncio.current_task().set_name("cli_session_manage")

    async def play_game(self, game: RemoteGameShadowCopy):
        handle = self._define_game_handlers(game)
        generator = game.track_remote()

        event = None
        while True:
            try:
                old_event = event
                while event is old_event:
                    try:
                        game_input = await handle(event)
                        event = await generator.asend(game_input)
                    except valid8.ValidationError as exc:
                        await aprint(exc)
            except StopAsyncIteration:
                break

        await self._show_game_end(game)

    @staticmethod
    def _define_game_handlers(game: RemoteGameShadowCopy):
        @multimethod
        async def handle(e: gev.GameEvent) -> Optional[gev.GameInputRequest]:
            raise NotImplementedError(e)

        # ----------------------------- Game node stages -----------------------------
        @handle.register
        async def handle(e: loveletter.game.PlayingRound) -> None:
            await print_header(f"ROUND {e.round_no}", filler="#")

        @handle.register
        async def handle(e: rnd.Turn) -> None:
            if e.turn_no > 1:
                await pause()  # give a chance to read what's happened before next turn
            player = game.get_player(e.current_player)
            is_client = player is game.client_player

            possessive = "Your" if is_client else f"{player.username}'s"
            await print_header(f"{possessive} turn", filler="—")
            await draw_game(game, reveal=not game.client_player.round_player.alive)
            if is_client:
                await aprint(">>>>> It's your turn! <<<<<")
            else:
                await aprint(f"It's {player.username}'s turn.")

        @handle.register
        async def handle(e: rnd.PlayingCard) -> None:
            player, card = game.get_player(e.player), e.card
            is_client = player is game.client_player
            await aprint(
                f"{'You' if is_client else player.username} "
                f"{'have' if is_client else 'has'} chosen to play a {card.name}."
            )

        @handle.register
        async def handle(e: rnd.RoundEnd) -> None:
            get_username = lambda p: game.get_player(p).username  # noqa

            await pause()  # give a chance to see what's happened before the round end
            await print_header("Round end", filler="—")
            await draw_game(game, reveal=True)

            await aprint(">>>>> The round has ended! <<<<<")
            if e.reason == rnd.RoundEnd.Reason.EMPTY_DECK:
                await aprint("There are no cards remaining in the deck.")
                if len(e.tie_contenders) == 1:
                    await aprint(
                        f"{get_username(e.winner)} wins with a {e.winner.hand.card}, "
                        f"which is the highest card among those remaining."
                    )
                else:
                    card = mitt.first(p.hand.card for p in e.tie_contenders)
                    contenders = list(map(get_username, e.tie_contenders))
                    contenders_str = (
                        f"Both {contenders[0]} and {contenders[1]}"
                        if len(contenders) == 2
                        else f"Each of {', '.join(contenders[:-1])} and {contenders[-1]}"
                    )
                    await aprint(f"{contenders_str} have the highest card: a {card}.")
                    await aprint(
                        f"But {get_username(e.winner)} has a higher sum of discarded"
                        f" values, so they win."
                        if len(e.winners) == 1
                        else f"And they each have the same sum of discarded values,"
                        f" so they {'both' if len(contenders) == 2 else 'all'} win"
                        f" in a tie."
                    )
            elif e.reason == rnd.RoundEnd.Reason.ONE_PLAYER_STANDING:
                await aprint(
                    f"{get_username(e.winner)} is the only player still alive, "
                    f"so they win the round."
                )

        @handle.register
        async def handle(e: loveletter.game.PointsUpdate) -> None:
            # print updates from last round
            await aprint("Points gained:")
            for player, delta in (+e.points_update).items():
                await aprint(f"    {player.username}: {delta:+}")
            await aprint()
            await aprint("Leaderboard:")
            width = max(map(len, (p.username for p in game.players))) + 2
            for i, (player, points) in enumerate(game.points.most_common(), start=1):
                await aprint(
                    f"\t{i}. {player.username:{width}}"
                    f"\t{points} {pluralize('token', points)} of affection"
                )
            await aprint()
            await pause()  # before going on to next round

        # ------------------------------ Remote events -------------------------------
        @handle.register
        async def handle(e: RemoteEvent) -> None:
            message = f"{e.description}..."
            if isinstance(e.wrapped, mv.MoveStep):
                name = e.wrapped.__class__.__name__
                message += f" ({camel_to_phrase(name)})"
            await aprint(message)

        # ----------------------------- Pre-move choices -----------------------------
        @handle.register
        async def handle(e: rnd.FirstPlayerChoice) -> rnd.FirstPlayerChoice:
            e.choice = await _player_choice(prompt="Who goes first?")
            return e

        @handle.register
        async def handle(e: rnd.ChooseCardToPlay) -> rnd.ChooseCardToPlay:
            choice = await async_ask_valid_input(
                "What card do you want to play?", choices=MoveChoice
            )
            e.choice = mitt.nth(game.current_round.current_player.hand, choice.value)
            return e

        # -------------------------------- Move steps --------------------------------
        @handle.register
        async def handle(e: mv.CardGuess):
            # noinspection PyArgumentList
            choices = enum.Enum(
                "CardGuess",
                names={
                    n: m for n, m in CardType.__members__.items() if m != CardType.GUARD
                },
            )
            choice = await async_ask_valid_input("Guess a card:", choices=choices)
            e.choice = choice.value
            return e

        @handle.register
        async def handle(e: mv.PlayerChoice):
            e.choice = await _player_choice(
                prompt="Choose a target (you can choose yourself):"
            )
            return e

        @handle.register
        async def handle(e: mv.OpponentChoice):
            # auto-choose opponent if there are only 2 players and no immune players
            if game.num_players == 2 and e.options != {e.NO_TARGET}:
                e.choice = mitt.one(e.options)
            else:
                e.choice = await _player_choice(
                    prompt="Choose an opponent to target:", include_self=False
                )
            return e

        @handle.register
        async def handle(e: mv.ChooseOneCard):
            num_drawn = len(e.options) - 1
            names = [CardType(c).name.title() for c in e.options]
            options_members = {CardType(c).name: c for c in e.options}

            await aprint(
                f"You draw {num_drawn} {pluralize('card', num_drawn)}; "
                f"you now have these cards in your hand: {', '.join(names)}"
            )
            # noinspection PyArgumentList
            choices = enum.Enum("CardOption", names=options_members)
            choice = await async_ask_valid_input("Choose one card:", choices=choices)
            e.choice = choice.value
            return e

        @handle.register
        async def handle(e: mv.ChooseOrderForDeckBottom):
            if len(e.cards) == 0:
                e.choice = ()
                return e

            fmt = ", ".join(f"{i}: {CardType(c).name}" for i, c in enumerate(e.cards))
            await aprint(f"Leftover cards: {fmt}")
            await aprint(
                "You can choose which order to place these cards at the bottom of the "
                "deck. Use the numbers shown above to refer to each of the cards."
            )

            idx_range = range(len(e.cards))

            def parser(s: str) -> Tuple[int, ...]:
                nums = tuple(map(int, s.split(",")))
                valid8.validate(
                    "nums",
                    set(nums),
                    equals=set(idx_range),
                    help_msg="Each number in {numbers} should appear exactly"
                    " once, and nothing else.",
                    numbers=set(idx_range),
                )
                return nums

            example = list(idx_range)
            random.shuffle(example)
            prompt = (
                f"Choose an order to place these cards at the bottom of the deck "
                f"as a comma-separated list of integers, from TOPMOST to "
                f"BOTTOMMOST (in the order that they will be drawn)"
                f" — e.g. {', '.join(map(str, example))}):"
            )
            choice = await async_ask_valid_input(prompt, parser=parser)
            e.set_from_serializable(choice)
            return e

        # ------------------------------- Move results -------------------------------
        @handle.register
        async def handle(e: mv.CorrectCardGuess) -> None:
            player, opponent = map(game.get_player, (e.player, e.opponent))
            is_client = player is game.client_player
            target_is_client = opponent is game.client_player
            possessive = "your" if target_is_client else f"{opponent.username}'s"
            await aprint(
                f"{'You' if is_client else player.username} correctly guessed "
                f"{possessive} {e.guess.name.title()}!"
            )

        @handle.register
        async def handle(e: mv.WrongCardGuess) -> None:
            player, opponent = map(game.get_player, (e.player, e.opponent))
            if player is game.client_player:
                await aprint(
                    f"You played a Guard against {opponent.username} and guessed a "
                    f"{e.guess.name.title()}, but {opponent.username} doesn't have "
                    f"that card."
                )
            elif opponent is game.client_player:
                await aprint(
                    f"{player.username} played a Guard against you and guessed a "
                    f"{e.guess.name.title()}, but you don't have that card."
                )
            else:
                await aprint(
                    f"{player.username} played a Guard against {opponent.username} "
                    f"and guessed a {e.guess.name.title()}, but {opponent.username} "
                    f"doesn't have that card."
                )

        @handle.register
        async def handle(e: mv.PlayerEliminated) -> None:
            player = game.get_player(e.eliminated)
            is_client = player is game.client_player
            message = (
                f"💀 {'You' if is_client else player.username} "
                f"{'have' if is_client else 'has'} been eliminated! 💀"
            )
            if not is_client:
                message += f" They had a {e.eliminated_card.name}."
            await aprint(message)

        @handle.register
        async def handle(e: mv.ShowOpponentCard) -> None:
            player, opponent = map(game.get_player, (e.player, e.opponent))
            if player is game.client_player:
                await aprint(
                    f"{opponent.username} shows their card to you, "
                    f"revealing a {e.card_shown.name}."
                )
            elif opponent is game.client_player:
                await aprint(f"You show your {e.card_shown.name} to {player.username}.")
            else:
                await aprint(
                    f"{opponent.username} shows their card to {player.username}."
                )

        @handle.register
        async def handle(e: mv.CardComparison) -> None:
            player, opponent = map(game.get_player, (e.player, e.opponent))
            if player is game.client_player:
                await aprint(
                    f"You and {opponent.username} compare your cards: "
                    f"you have a {e.player_card.name}, "
                    f"they have a {e.opponent_card.name}."
                )
            elif opponent is game.client_player:
                await aprint(
                    f"{player.username} compares their hand with yours: "
                    f"they have a {e.player_card.name}, "
                    f"you have a {e.opponent_card.name}."
                )
            else:
                await aprint(
                    f"{player.username} and {opponent.username} "
                    f"compare their cards in secret."
                )

        @handle.register
        async def handle(e: mv.CardDiscarded) -> None:
            player = game.get_player(e.target)
            is_client = player is game.client_player
            await aprint(
                f"{'You' if is_client else player.username} "
                f"discard{'s' if not is_client else ''} a {e.discarded.name}."
            )

        @handle.register
        async def handle(e: mv.CardDealt) -> None:
            player = game.get_player(e.target)
            is_client = player is game.client_player
            await aprint(
                f"{'You' if is_client else player.username} "
                f"{'are' if is_client else 'is'} dealt another card from the deck."
            )
            if is_client:
                await aprint(f"You get a {e.card_dealt.name}.")

        @handle.register
        async def handle(e: mv.CardChosen) -> None:
            player = game.get_player(e.player)
            if player is game.client_player:
                await aprint(f"You have chosen to keep the {e.choice.name}.")
            else:
                await aprint(f"{player.username} has chosen a card to keep.")

        @handle.register
        async def handle(e: mv.CardsPlacedBottomOfDeck) -> None:
            player = game.get_player(e.player)
            is_client = player is game.client_player
            await aprint(
                f"{'You' if is_client else player.username} "
                f"{'have' if is_client else 'has'} placed back the other "
                f"{len(e.cards)} {pluralize('card', len(e.cards))} "
                f"at the bottom of the deck."
            )

        @handle.register
        async def handle(e: mv.ImmunityGranted) -> None:
            player = game.get_player(e.player)
            is_client = player is game.client_player
            await aprint(
                f"{'You' if is_client else player.username} "
                f"{'have' if is_client else 'has'} been granted immunity."
            )

        @handle.register
        async def handle(e: mv.CardsSwapped) -> None:
            king_player, target = map(game.get_player, (e.player, e.opponent))
            if game.client_player in (king_player, target):
                opponent = target if game.client_player is king_player else king_player
                await aprint(f"You and {opponent.username} swap your cards.")
                await aprint(f"You give a {opponent.round_player.hand.card.name}.")
                await aprint(
                    f"You get a {game.client_player.round_player.hand.card.name}."
                )
            else:
                await aprint(
                    f"{king_player.username} and {target.username} swap their cards."
                )

        # --------------------------------- Helpers ----------------------------------
        async def _player_choice(
            prompt: str, include_self=True
        ) -> loveletter.game.Game.Player:
            options = set(map(game.get_player, game.current_round.targetable_players))
            if not include_self:
                options -= {game.client_player}
            if options:
                # noinspection PyArgumentList
                choices = enum.Enum(
                    "Player",
                    names={
                        p.username: game.current_round.players[p.id] for p in options
                    },
                )
                choice = await async_ask_valid_input(prompt, choices=choices)
                return choice.value
            else:
                await aprint(
                    "There are no valid targets, playing this card has no effect."
                )
                # TODO: allow cancel
                return mv.OpponentChoice.NO_TARGET

        @handle.register
        async def handle(e: None):  # special case for first "event" in loop below
            return e

        # return the multimethod object; contains all branches
        return handle

    @staticmethod
    async def _show_game_end(game: RemoteGameShadowCopy):
        assert game.ended
        await print_header("GAME OVER", filler="#")
        end: loveletter.game.GameEnd = game.state  # noqa
        try:
            winner = end.winner
        except ValueError:
            await print_centered("There were multiple winners!")
            winner_message = (
                f"{', '.join(p.username for p in end.winners)} all won in a tie."
            )
        else:
            if winner is game.client_player:
                winner_message = "You win!"
            else:
                winner_message = f"{winner.username} wins!"

        await print_centered(f"🏆🏆🏆 {winner_message} 🏆🏆🏆")
        await aprint()


class HostCLISession(CommandLineSession):
    server_address: Address
    client: HostClient

    def __init__(
        self,
        user: UserInfo,
        server_address: Address,
    ):
        super().__init__(user)
        self.client = HostClient(
            user.username,
            player_joined_callback=self._player_joined,
            player_left_callback=self._player_left,
        )
        self.server_address = server_address
        self._host_has_joined_server: Optional[asyncio.Event] = None

    async def manage(self):
        await super().manage()
        self._host_has_joined_server = asyncio.Event()
        await aprint("Joining the server...", end=" ")  # see _player_joined()
        connection_task = await self._connect()
        await self._host_has_joined_server.wait()
        await watch_task(
            connection_task, main_task=self._manage_after_connection_established()
        )

    async def _manage_after_connection_established(self):
        game = await self._ready_to_play()
        await self.play_game(game)
        await self.client.send_shutdown()

    async def _connect(self) -> asyncio.Task:
        # give the server process enough time to start up
        backoff = 0.25  # time in seconds between attempts
        for attempt in range(3):
            try:
                return await self.client.connect(*self.server_address)
            except ConnectionRefusedError as e:
                error = e
                await asyncio.sleep(backoff)
                backoff *= 2
        else:
            # noinspection PyUnboundLocalVariable
            raise error

    async def _ready_to_play(self) -> RemoteGameShadowCopy:
        await aprint("Waiting for other players to join the server.")
        game = None
        while game is None:
            await ainput("Enter anything when ready to play...\n")
            await self.client.ready()
            try:
                game = await self.client.wait_for_game()
            except RemoteValidationError as e:
                await aprint(e.help_message, end="\n\n")
            except RemoteException as e:
                await aprint("Error in server while creating game:")
                await print_exception(e)

        return game

    async def _player_joined(self, message: msg.PlayerJoined):
        if message.username == self.user.username:
            await aprint("Done.")  # see manage()
            self._host_has_joined_server.set()
        else:
            await self._host_has_joined_server.wait()  # synchronize prints
            await aprint(f"{message.username} joined the server")

    @staticmethod
    async def _player_left(message: msg.PlayerDisconnected):
        await aprint(f"{message.username} left the server")


class HostWithLocalServerCLISession(HostCLISession):
    hosts: Tuple[str, ...]
    port: int

    def __init__(
        self,
        user: UserInfo,
        hosts: Tuple[str],
        port: int,
        show_server_logs: bool = False,
    ):
        super().__init__(user, Address("127.0.0.1", port))
        self.hosts = hosts
        self.port = port
        self.show_server_logs = show_server_logs

    @property
    def server_addresses(self) -> Tuple[Address, ...]:
        return tuple(Address(h, self.port) for h in self.hosts)

    async def manage(self):
        await print_header(
            f"Hosting game on {', '.join(f'{h}:{p}' for h, p in self.server_addresses)}"
        )
        with self._configure_server_process():
            return await super().manage()

    def _configure_server_process(self) -> ServerProcess:
        """Subclasses can override this to customise the server process."""
        return ServerProcess.new(
            hosts=self.hosts,
            port=self.port,
            host_user=self.user,
            show_logs=self.show_server_logs,
        )


class GuestCLISession(CommandLineSession):

    client: GuestClient
    server_address: Address

    def __init__(self, user: UserInfo, server_address: Address):
        super().__init__(user)
        self.client = GuestClient(user.username)
        self.server_address = server_address

    async def manage(self):
        await super().manage()
        address = self.server_address
        await print_header(f"Joining game @ {address.host}:{address.port}")
        connection_task = await self._connect_to_server()
        await watch_task(
            connection_task, main_task=self._manage_after_connection_established()
        )

    async def _manage_after_connection_established(self):
        game = await self._wait_for_game()
        await self.play_game(game)

    async def _connect_to_server(self) -> asyncio.Task:
        class ConnectionErrorOptions(enum.Enum):
            RETRY = "retry"
            RESTART = "restart"
            QUIT = "quit"

        while True:
            try:
                connection = await self.client.connect(*self.server_address)
                break
            except asyncio.exceptions.TimeoutError:
                await aprint("Connection attempt timed out.", end="\n\n")
            except (OSError, LogonError) as e:
                await aprint("Error while trying to connect to the server:")
                await print_exception(e)

            choice = await async_ask_valid_input(
                "What would you like to do? ("
                "RETRY: retry connecting to this server; "
                "RESTART: restart Love Letter CLI (go back to username selection); "
                "QUIT: quit Love Letter CLI"
                ")",
                choices=ConnectionErrorOptions,
                default=ConnectionErrorOptions.RETRY,
            )
            if choice == ConnectionErrorOptions.RETRY:
                continue
            elif choice == ConnectionErrorOptions.RESTART:
                raise Restart from None
            elif choice == ConnectionErrorOptions.QUIT:
                sys.exit(1)
            else:
                assert False

        await aprint("Successfully connected to the server.")
        # noinspection PyUnboundLocalVariable
        return connection

    async def _wait_for_game(self) -> RemoteGameShadowCopy:
        await aprint("Waiting for the host to start the game...")
        return await self.client.wait_for_game()
