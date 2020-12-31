import asyncio
import enum
import logging
from dataclasses import dataclass
from typing import Tuple

from loveletter_cli.utils import print_header
from loveletter_multiplayer import HostClient
from loveletter_multiplayer.utils import Address


LOGGER = logging.getLogger(__name__)


@dataclass
class CommandLineSession:
    """CLI session manager."""

    user: "UserInfo"

    async def host_game(self, hosts: Tuple[str], port: int):
        print_header(f"Hosting game on {', '.join(f'{h}:{port}' for h in hosts)}")
        script_path = "loveletter_cli.server_script"
        # for now Windows-only (start is a cmd shell thing)
        args = [
            *hosts,
            port,
            self.user.username,
            "--logging",
            LOGGER.getEffectiveLevel(),
        ]
        args = list(map(str, args))
        cmd = f'start "{script_path}" /wait python -m {script_path} {" ".join(args)}'
        LOGGER.debug(f"Starting server script with {repr(cmd)}")
        server_process = await asyncio.create_subprocess_shell(cmd)
        try:
            client = HostClient(self.user.username)
            await client.connect("127.0.0.1", port)
            input("Press any key when ready to play...")
            await client.ready()  # TODO: check response from server
            # TODO: actual game here...
        finally:
            await server_process.wait()

    async def join_game(self, address: Address):
        pass


@dataclass(frozen=True)
class UserInfo:
    username: str


class PlayMode(enum.Enum):
    HOST = enum.auto()  #: host a game
    JOIN = enum.auto()  #: join an existing game


class HostVisibility(enum.Enum):
    LOCAL = enum.auto()  #: local network only
    PUBLIC = enum.auto()  #: visible from the internet
