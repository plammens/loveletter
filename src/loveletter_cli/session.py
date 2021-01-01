import abc
import asyncio
import enum
import logging
import random
import subprocess
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
from loveletter_cli.ui import async_ask_valid_input, draw_game, print_exception
from loveletter_cli.utils import print_header
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
        @multimethod
        async def handle(e: gev.GameEvent) -> Optional[gev.GameInputRequest]:
            raise NotImplementedError(e)

        @handle.register
        async def handle(e: gev.GameResultEvent) -> None:
            print(e)

        @handle.register
        async def handle(e: RemoteEvent) -> None:
            print(f"{e.description}...")

        @handle.register
        async def handle(e: rnd.FirstPlayerChoice) -> rnd.FirstPlayerChoice:
            e.choice = await _player_choice(prompt="Who goes first?")
            return e

        @handle.register
        async def handle(e: rnd.PlayerMoveChoice) -> rnd.PlayerMoveChoice:
            choice = await async_ask_valid_input(
                "What card do you want to play?", choices=MoveChoice
            )
            e.choice = mitt.nth(game.current_round.current_player.hand, choice.value)
            return e

        @handle.register
        async def handle(e: mv.CardGuess):
            e.choice = await async_ask_valid_input("Guess a card:", choices=CardType)
            return e

        @handle.register
        async def handle(e: mv.PlayerChoice):
            e.choice = await _player_choice(
                prompt="Choose a target (you can choose yourself):"
            )
            return e

        @handle.register
        async def handle(e: mv.OpponentChoice):
            e.choice = await _player_choice(prompt="Choose an opponent to target:")
            return e

        @handle.register
        async def handle(e: mv.ChooseOneCard):
            choices = enum.Enum(
                "CardOption", names=(CardType(c).name for c in e.options), start=0
            )
            choice = await async_ask_valid_input("Choose one card:", choices=choices)
            e.choice = e.options[choice.value]
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
                f"Choose an order to place these cards at the bottom of the deck\n"
                f"    as a comma-separated list of integers, from bottommost to\n"
                f"    topmost (e.g. {', '.join(map(str, example))}):"
            )
            choice = await async_ask_valid_input(prompt, parser=parser)
            e.set_from_serializable(choice)
            return e

        async def _player_choice(prompt: str) -> loveletter.game.Game.Player:
            choices = enum.Enum(
                "FirstPlayer", names=[p.username for p in game.players], start=0
            )
            choice = await async_ask_valid_input(prompt, choices=choices)
            return game.current_round.players[choice.value]

        generator = game.track_remote()
        game_input = None
        while True:
            try:
                event = await generator.asend(game_input)
            except StopAsyncIteration:
                break

            while True:
                try:
                    game_input = await handle(event)
                except valid8.ValidationError as exc:
                    print(exc)
                else:
                    break

            draw_game(game)

        await self._show_game_end(game)

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
            if winner.id == game.client_player_id:
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
        await super().manage()
        print_header(
            f"Hosting game on {', '.join(f'{h}:{p}' for h, p in self.server_addresses)}"
        )
        script_path = "loveletter_cli.server_script"
        # for now Windows-only (start is a cmd shell thing)
        args = [
            *self.hosts,
            self.port,
            self.user.username,
            "--logging",
            LOGGER.getEffectiveLevel(),
        ]
        args = subprocess.list2cmdline(list(map(str, args)))
        cmd = f'start "{script_path}" /wait python -m {script_path} {args}'
        LOGGER.debug(f"Starting server script with {repr(cmd)}")
        server_process = await asyncio.create_subprocess_shell(cmd)
        try:
            self.client = HostClient(self.user.username)
            await self._connect_localhost()
            game = await self._ready_to_play()
            await self.play_game(game)
        finally:
            if (exc_info := sys.exc_info()) == (None, None, None):
                LOGGER.info("Waiting on server process to end")
            else:
                LOGGER.warning(
                    "manage raised, waiting on server process to end", exc_info=exc_info
                )
            await server_process.wait()
            LOGGER.debug("Server process ended")

    async def _connect_localhost(self):
        connection = await self.client.connect("127.0.0.1", self.port)
        watch_connection(connection)

    async def _ready_to_play(self) -> RemoteGameShadowCopy:
        game = None
        while game is None:
            await ainput("Enter something when ready to play... ")
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
        await self._connect_to_server()
        game = await self.client.wait_for_game()
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

        watch_connection(connection)
        return connection


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
