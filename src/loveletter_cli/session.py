import abc
import asyncio
import enum
import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Tuple

from aioconsole import ainput

from loveletter_cli.ui import async_ask_valid_input, print_exception
from loveletter_cli.utils import print_header
from loveletter_multiplayer import (
    GuestClient,
    HostClient,
    LogonError,
    RemoteException,
    RemoteGameShadowCopy,
)
from loveletter_multiplayer.client import watch_connection
from loveletter_multiplayer.utils import Address


LOGGER = logging.getLogger(__name__)


@dataclass
class CommandLineSession(metaclass=abc.ABCMeta):
    """CLI session manager."""

    user: "UserInfo"

    @abc.abstractmethod
    async def manage(self):
        """Main entry point to run and manage this session."""
        asyncio.current_task().set_name("cli_session_manage")


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
            # TODO: actual game here...
            await asyncio.sleep(100)
        finally:
            if sys.exc_info() == (None, None, None):
                LOGGER.info("Waiting on server process to end")
            else:
                LOGGER.warning("manage raised, waiting on server process to end")
            await server_process.wait()

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
        # TODO: actual game logic...
        await asyncio.sleep(100)

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
