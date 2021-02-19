import abc
import asyncio
import enum
import logging
import multiprocessing
import random
import sys
from dataclasses import dataclass, field
from typing import Optional, Tuple

import more_itertools as mitt
from aioconsole import ainput
from multimethod import multimethod

import loveletter.game
import loveletter.gameevent as gev
import loveletter.move as mv
import loveletter.round as rnd
from loveletter.cards import CardType
from loveletter_cli.ui import (
    async_ask_valid_input,
    draw_game,
    pause,
    pluralize,
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
    valid8,
)
from loveletter_multiplayer.client import LoveletterClient, watch_connection
from loveletter_multiplayer.utils import Address


LOGGER = logging.getLogger(__name__)


@dataclass
class CommandLineSession(metaclass=abc.ABCMeta):
    """CLI session manager."""

    user: "UserInfo"
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
                        print(exc)
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
            if e.points_update:
                # print updates from last round
                print("Points gained:")
                for player, delta in (+e.points_update).items():
                    print(f"    {player.username}: {delta:+}")
                print()
                print("Leaderboard:")
                width = max(map(len, (p.username for p in game.players))) + 2
                for i, (player, points) in enumerate(
                    game.points.most_common(), start=1
                ):
                    print(
                        f"\t{i}. {player.username:{width}}"
                        f"\t{points} {pluralize('token', points)} of affection"
                    )
                print()
                await pause()

            print_header(f"ROUND {e.round_no}", filler="#")

        @handle.register
        async def handle(e: rnd.Turn) -> None:
            if e.turn_no > 1:
                await pause()
            player = game.get_player(e.current_player)
            is_client = player is game.client_player

            possessive = "Your" if is_client else f"{player.username}'s"
            print_header(f"{possessive} turn", filler="—")
            draw_game(game)
            if is_client:
                print(">>>>> It's your turn! <<<<<\a")
            else:
                print(f"It's {player.username}'s turn.")

        @handle.register
        async def handle(e: rnd.PlayingCard) -> None:
            player, card = game.get_player(e.player), e.card
            is_client = player is game.client_player
            print(
                f"{'You' if is_client else player.username} "
                f"{'have' if is_client else 'has'} chosen to play a {card.name}."
            )

        @handle.register
        async def handle(e: rnd.RoundEnd) -> None:
            get_username = lambda p: game.get_player(p).username  # noqa

            await pause()
            print_header("Round end", filler="—")
            draw_game(game, reveal=True)

            print(">>>>> The round has ended! <<<<<")
            if e.reason == rnd.RoundEnd.Reason.EMPTY_DECK:
                print("There are no cards remaining in the deck.")
                if len(e.tie_contenders) == 1:
                    print(
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
                    print(f"{contenders_str} have the highest card: a {card}.")
                    print(
                        f"But {e.winner} has a higher sum of discarded values,"
                        f" so they win."
                        if len(e.winners) == 1
                        else f"And they each have the same sum of discarded values,"
                        f" so they {'both' if len(contenders) == 2 else 'all'} win"
                        f" in a tie."
                    )
            elif e.reason == rnd.RoundEnd.Reason.ONE_PLAYER_STANDING:
                print(
                    f"{get_username(e.winner)} is the only player still alive, "
                    f"so they win the round."
                )
            # points update gets printed in PlayingRound handler

        # ------------------------------ Remote events -------------------------------
        @handle.register
        async def handle(e: RemoteEvent) -> None:
            msg = f"{e.description}..."
            if isinstance(e.wrapped, mv.MoveStep):
                name = e.wrapped.__class__.__name__
                msg += f" ({camel_to_phrase(name)})"
            print(msg)

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
            e.choice = await _player_choice(
                prompt="Choose an opponent to target:", include_self=False
            )
            return e

        @handle.register
        async def handle(e: mv.ChooseOneCard):
            num_drawn = len(e.options) - 1
            names = [CardType(c).name.title() for c in e.options]
            options_members = {CardType(c).name: c for c in e.options}

            print(
                f"You draw {num_drawn} {pluralize('card', num_drawn)}; "
                f"you now have these cards in your hand: {', '.join(names)}"
            )
            choices = enum.Enum("CardOption", names=options_members)
            choice = await async_ask_valid_input("Choose one card:", choices=choices)
            e.choice = choice.value
            return e

        @handle.register
        async def handle(e: mv.ChooseOrderForDeckBottom):
            fmt = ", ".join(f"{i}: {CardType(c).name}" for i, c in enumerate(e.cards))
            print(f"Leftover cards: {fmt}")
            print(
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
                    help_msg=f"Each number in {set(idx_range)} should appear exactly "
                    f"once, and nothing else.",
                )
                return nums

            example = list(idx_range)
            random.shuffle(example)
            prompt = (
                f"Choose an order to place these cards at the bottom of the deck "
                f"as a comma-separated list of integers, from bottommost to "
                f"topmost (e.g. {', '.join(map(str, example))}):"
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
            print(
                f"{'You' if is_client else player.username} correctly guessed "
                f"{possessive} {e.guess.name.title()}!"
            )

        @handle.register
        async def handle(e: mv.WrongCardGuess) -> None:
            player, opponent = map(game.get_player, (e.player, e.opponent))
            if player is game.client_player:
                print(
                    f"You played a Guard against {opponent.username} and guessed a "
                    f"{e.guess.name.title()}, but {opponent.username} doesn't have "
                    f"that card."
                )
            elif opponent is game.client_player:
                print(
                    f"{player.username} played a Guard against you and guessed a "
                    f"{e.guess.name.title()}, but you don't have that card."
                )
            else:
                print(
                    f"{player.username} played a Guard against {opponent.username} "
                    f"and guessed a {e.guess.name.title()}, but {opponent.username} "
                    f"doesn't have that card."
                )

        @handle.register
        async def handle(e: mv.PlayerEliminated) -> None:
            player = game.get_player(e.eliminated)
            is_client = player is game.client_player
            msg = (
                f"💀 {'You' if is_client else player.username} "
                f"{'have' if is_client else 'has'} been eliminated! 💀"
            )
            if not is_client:
                msg += f" They had a {e.eliminated_card.name}."
            print(msg)

        @handle.register
        async def handle(e: mv.ShowOpponentCard) -> None:
            player, opponent = map(game.get_player, (e.player, e.opponent))
            if player is game.client_player:
                print(
                    f"{opponent.username} shows their card to you, "
                    f"revealing a {e.card_shown.name}."
                )
            elif opponent is game.client_player:
                print(f"You show your {e.card_shown.name} to {player.username}.")
            else:
                print(f"{opponent.username} shows their card to {player.username}.")

        @handle.register
        async def handle(e: mv.CardComparison) -> None:
            player, opponent = map(game.get_player, (e.player, e.opponent))
            if player is game.client_player:
                print(
                    f"You and {opponent.username} compare your cards: "
                    f"you have a {e.player_card.name}, "
                    f"they have a {e.opponent_card.name}."
                )
            elif opponent is game.client_player:
                print(
                    f"{player.username} compares their hand with yours: "
                    f"they have a {e.player_card.name}, "
                    f"you have a {e.opponent_card.name}."
                )
            else:
                print(
                    f"{player.username} and {opponent.username} "
                    f"compare their cards in secret."
                )

        @handle.register
        async def handle(e: mv.CardDiscarded) -> None:
            player = game.get_player(e.target)
            is_client = player is game.client_player
            print(
                f"{'You' if is_client else player.username} "
                f"discard{'s' if not is_client else ''} a {e.discarded.name}."
            )

        @handle.register
        async def handle(e: mv.CardDealt) -> None:
            player = game.get_player(e.target)
            is_client = player is game.client_player
            print(
                f"{'You' if is_client else player.username} "
                f"{'are' if is_client else 'is'} dealt another card from the deck."
            )

        @handle.register
        async def handle(e: mv.CardChosen) -> None:
            player = game.get_player(e.player)
            if player is game.client_player:
                print(f"You have chosen to keep the {e.choice.name}.")
            else:
                print(f"{player.username} has chosen a card to keep.")

        @handle.register
        async def handle(e: mv.CardsPlacedBottomOfDeck) -> None:
            player = game.get_player(e.player)
            is_client = player is game.client_player
            print(
                f"{'You' if is_client else player.username} "
                f"{'have' if is_client else 'has'} placed back the other "
                f"{len(e.cards)} {pluralize('card', len(e.cards))} "
                f"at the bottom of the deck."
            )

        @handle.register
        async def handle(e: mv.ImmunityGranted) -> None:
            player = game.get_player(e.player)
            is_client = player is game.client_player
            print(
                f"{'You' if is_client else player.username} "
                f"{'have' if is_client else 'has'} been granted immunity."
            )

        @handle.register
        async def handle(e: mv.CardsSwapped) -> None:
            player, opponent = map(game.get_player, (e.player, e.opponent))
            is_client = player is game.client_player
            print(
                f"{'You' if is_client else player.username} and {opponent.username}"
                f"swap {'your' if is_client else 'their'} cards."
            )

        # --------------------------------- Helpers ----------------------------------
        async def _player_choice(
            prompt: str, include_self=True
        ) -> loveletter.game.Game.Player:
            options = set(map(game.get_player, game.current_round.targetable_players))
            if not include_self:
                options -= {game.client_player}
            if options:
                choices = enum.Enum(
                    "Player",
                    names={
                        p.username: game.current_round.players[p.id] for p in options
                    },
                )
                choice = await async_ask_valid_input(prompt, choices=choices)
                return choice.value
            else:
                print(
                    "There are no valid targets (all living opponents are immune); "
                    "playing this card will have no effect."
                )
                await pause()
                return mv.OpponentChoice.NO_TARGET

        @handle.register
        async def handle(e: None):  # special case for first "event" in loop below
            return e

        # return the multimethod object; contains all branches
        return handle

    @staticmethod
    async def _show_game_end(game: RemoteGameShadowCopy):
        assert game.ended
        print_header("GAME OVER", filler="#")
        end: loveletter.game.GameEnd = game.state  # noqa
        try:
            winner = end.winner
        except ValueError:
            print("There were multiple winners!")
            print(f"{', '.join(p.username for p in end.winners)} all won in a tie.")
        else:
            if winner is game.client_player:
                print("You win!")
            else:
                print(f"{winner.username} wins!")


class HostCLISession(CommandLineSession):

    hosts: Tuple[str, ...]
    port: int
    client: HostClient

    def __init__(self, user: "UserInfo", hosts: Tuple[str], port: int):
        super().__init__(user)
        self.hosts = hosts
        self.port = port
        self.client = HostClient(user.username)

    @property
    def server_addresses(self) -> Tuple[Address, ...]:
        return tuple(Address(h, self.port) for h in self.hosts)

    async def manage(self):
        import loveletter_cli.server_script

        await super().manage()
        print_header(
            f"Hosting game on {', '.join(f'{h}:{p}' for h, p in self.server_addresses)}"
        )
        server_process = multiprocessing.Process(
            target=loveletter_cli.server_script.main,
            kwargs=dict(
                logging_level=LOGGER.getEffectiveLevel(),
                host=self.hosts,
                port=self.port,
                party_host_username=self.user.username,
            ),
        )
        LOGGER.debug(f"Starting server process: %s", server_process)
        server_process.start()
        try:
            self.client = HostClient(self.user.username)
            connection = await self._connect_localhost()
            game = await self._ready_to_play()
            await self.play_game(game)
            await self.client.send_shutdown()
            await connection
        finally:
            if (exc_info := sys.exc_info()) == (None, None, None):
                LOGGER.info("Waiting on server process to end")
            else:
                LOGGER.warning(
                    "manage raised, waiting on server process to end", exc_info=exc_info
                )
            server_process.join(5)
            LOGGER.debug("Server process ended")

    async def _connect_localhost(self) -> asyncio.Task:
        connection = await self.client.connect("127.0.0.1", self.port)
        watch_connection(connection)
        return connection

    async def _ready_to_play(self) -> RemoteGameShadowCopy:
        game = None
        while game is None:
            await ainput("Enter anything when ready to play... ")
            await self.client.ready()
            try:
                game = await self.client.wait_for_game()
            except RemoteException as e:
                print("Exception in server while creating game:")
                print_exception(e)
                continue
        return game


class GuestCLISession(CommandLineSession):

    client: GuestClient
    server_address: Address

    def __init__(self, user: "UserInfo", server_address: Address):
        super().__init__(user)
        self.client = GuestClient(user.username)
        self.server_address = server_address

    async def manage(self):
        await super().manage()
        address = self.server_address
        print_header(f"Joining game @ {address.host}:{address.port}")
        await self._connect_to_server()
        game = await self._wait_for_game()
        await self.play_game(game)

    async def _connect_to_server(self) -> asyncio.Task:
        class ConnectionErrorOptions(enum.Enum):
            RETRY = enum.auto()
            ABORT = enum.auto()
            QUIT = enum.auto()

        connection = None
        while connection is None:
            try:
                connection = await self.client.connect(*self.server_address)
            except (ConnectionError, LogonError) as e:
                print("Error while trying to connect to the server:")
                print_exception(e)
                choice = await async_ask_valid_input(
                    "What would you like to do?",
                    choices=ConnectionErrorOptions,
                    default=ConnectionErrorOptions.RETRY,
                )
                if choice == ConnectionErrorOptions.RETRY:
                    continue
                elif choice == ConnectionErrorOptions.ABORT:
                    raise
                elif choice == ConnectionErrorOptions.QUIT:
                    sys.exit(1)
                else:
                    assert False

        print("Successfully connected to the server.")
        watch_connection(connection)
        return connection

    async def _wait_for_game(self) -> RemoteGameShadowCopy:
        print("Waiting for the host to start the game...")
        return await self.client.wait_for_game()


@dataclass(frozen=True)
class UserInfo:
    username: str


class PlayMode(enum.Enum):
    HOST = enum.auto()  #: host a game
    JOIN = enum.auto()  #: join an existing game


class HostVisibility(enum.Enum):
    LOCAL = enum.auto()  #: local network only
    PUBLIC = enum.auto()  #: visible from the internet


class MoveChoice(enum.Enum):
    LEFT = 0
    RIGHT = 1
