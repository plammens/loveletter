import argparse
import asyncio
import functools
import logging
import multiprocessing
import pathlib
import socket
import sys
import time
import traceback

from aioconsole import aprint

from loveletter_cli.data import *
from loveletter_cli.exceptions import Restart
from loveletter_cli.session import (
    GuestCLISession,
    HostCLISession,
    HostWithLocalServerCLISession,
)
from loveletter_cli.ui import async_ask_valid_input, print_exception, print_header
from loveletter_cli.utils import (
    get_local_ip,
    get_public_ip,
    running_as_pyinstaller_executable,
)
from loveletter_multiplayer import DEFAULT_PORT, MAX_PORT, valid8
from loveletter_multiplayer.logging import setup_logging
from loveletter_multiplayer.utils import Address


LOGGER = logging.getLogger(__name__)


class UnhandledExceptionOptions(enum.Enum):
    RESTART = "restart"
    QUIT = "quit"


class GameEndOptions(enum.Enum):
    PLAY_AGAIN = "play_again"
    RESTART = "restart"
    QUIT = "quit"


def show_version():
    """What runs when --version is passed."""
    print(f"Loveletter CLI version {get_version()}")


def get_version() -> str:
    """Get the version of this project from the version file or from Git."""
    if running_as_pyinstaller_executable():
        # noinspection PyUnresolvedReferences
        path = pathlib.Path(sys._MEIPASS).resolve() / "__version__.txt"
        return path.read_text().strip()
    else:
        # should only run in development mode
        import setuptools_scm

        return setuptools_scm.get_version()


def main(
    show_client_logs: bool, show_server_logs: bool, logging_level: int = logging.INFO
):
    setup_logging(
        logging_level,
        file_path=(None if show_client_logs else pathlib.Path("./loveletter_cli.log")),
    )

    async def async_main():
        version = get_version()

        runners = {
            PlayMode.JOIN: join_game,
            PlayMode.HOST: functools.partial(
                host_game, show_server_logs=show_server_logs
            ),
        }
        while True:
            try:
                await print_header(
                    f"Welcome to Love Letter (CLI)! [v{version}]", filler="~"
                )

                user = await ask_user()
                await aprint(f"Welcome, {user.username}!")

                mode = await ask_play_mode()
                await aprint()
                return await runners[mode](user)
            except Restart:
                LOGGER.info("Restarting CLI")
                continue
            except Exception as e:
                LOGGER.error("Unhandled exception in CLI", exc_info=e)

                traceback.print_exc()
                time.sleep(0.2)
                await aprint("Unhandled exception:")
                await print_exception(e)
                time.sleep(0.2)

                choice = await async_ask_valid_input(
                    "What would you like to do?",
                    choices=UnhandledExceptionOptions,
                    default=UnhandledExceptionOptions.RESTART,
                )
                if choice == UnhandledExceptionOptions.RESTART:
                    continue
                elif choice == UnhandledExceptionOptions.QUIT:
                    return
                else:
                    assert False, f"Unhandled error option: {choice}"

    asyncio.run(async_main())


async def ask_user():
    def parser(x: str) -> str:
        x = x.strip()
        x = " ".join(x.split())  # normalize spaces to 1 space
        valid8.validate(
            "username",
            x,
            empty=False,
            custom=lambda s: all(map(str.isalnum, s.split())),
            help_msg="Username should be non-empty"
            " and consist of letters, numbers and spaces only",
        )
        return x

    username = await async_ask_valid_input("Enter your username: ", parser=parser)
    user = UserInfo(username)
    return user


async def ask_play_mode() -> PlayMode:
    prompt = f"Would you like to host a game or join an existing one? "
    error_message = "Not a valid mode: {choice!r}"
    return await async_ask_valid_input(
        prompt=prompt,
        choices=PlayMode,
        error_message=error_message,
        validation_errors=(KeyError,),
    )


async def host_game(user: UserInfo, show_server_logs: bool):
    await print_header("Hosting a game")

    server_location = await async_ask_valid_input(
        "Do you want to use an external server or host one locally?",
        choices=ServerLocation,
        default=ServerLocation.LOCAL,
    )

    if server_location == ServerLocation.LOCAL:
        visibility = await async_ask_valid_input(
            "Choose the server's visibility:",
            choices=HostVisibility,
            default=HostVisibility.PUBLIC,
        )
        addresses = {"local": get_local_ip()}
        if visibility == HostVisibility.PUBLIC:
            addresses["public"] = get_public_ip()
            hosts = ("",)
        else:
            hosts = (
                "127.0.0.1",
                str(addresses["local"]),
            )  # allow either localhost or local net.
        await aprint(
            f"Your address: {' | '.join(f'{v} ({k})' for k, v in addresses.items())}"
        )
        port = await ask_port_for_hosting()

        def create_session():
            return HostWithLocalServerCLISession(
                user, hosts, port, show_server_logs=show_server_logs
            )

    elif server_location == ServerLocation.EXTERNAL:
        address = await ask_address_for_joining()

        def create_session():
            return HostCLISession(user, address)

    else:
        assert False, f"Unhandled server location: {server_location}"

    play_again = True
    while play_again:
        session = create_session()
        await session.manage()

        play_again = await ask_play_again()


async def ask_port_for_hosting() -> int:
    def parser(s: str) -> int:
        port = int(s)
        if not (socket.IPPORT_USERRESERVED <= port <= MAX_PORT):
            raise ValueError(port)
        return port

    return await async_ask_valid_input(
        prompt=(
            f"Choose a port number >= {socket.IPPORT_USERRESERVED}, <= {MAX_PORT}:"
        ),
        parser=parser,
        default=DEFAULT_PORT,
        error_message="Not a valid, non-reserved, port: {choice}",
    )


async def join_game(user: UserInfo):
    await print_header("Joining game")
    address = await ask_address_for_joining()

    play_again = True
    while play_again:
        session = GuestCLISession(user, address)
        await session.manage()

        play_again = await ask_play_again()


async def ask_address_for_joining() -> Address:
    def parser(s: str) -> Address:
        host, port = s.rsplit(":", maxsplit=1)
        port = int(port)
        with valid8.validation("host", host, help_msg="Invalid host"):
            host = socket.gethostbyname(host)
        port = int(port)
        valid8.validate("port", port, min_value=1, max_value=1 << 16, max_strict=True)
        return Address(host, port)

    return await async_ask_valid_input(
        prompt='Enter the server\'s address: (format: "<host>:<port>")',
        parser=parser,
    )


async def ask_play_again() -> bool:
    """
    Ask whether to play again after a session has ended.

    :return: Whether the user wants to play again.
    :raises Restart: if the user wants to restart the CLI (main menu).
    """
    choice = await async_ask_valid_input(
        prompt="The game has ended, what would you like to do?",
        choices=GameEndOptions,
    )
    if choice == GameEndOptions.PLAY_AGAIN:
        return True
    elif choice == GameEndOptions.RESTART:
        raise Restart
    elif choice == GameEndOptions.QUIT:
        return False
    else:
        assert False, f"Unhandled choice: {choice!r}"


def logging_level(level: str) -> int:
    try:
        level = int(level)
    except ValueError:
        pass

    if isinstance(level, int):
        if level <= 0:
            raise ValueError(f"Level can't be negative: {level}")
        return level
    else:
        try:
            # noinspection PyUnresolvedReferences,PyProtectedMember
            return logging._nameToLevel[level]
        except KeyError:
            raise ValueError(f"Not a valid level name: {level}")


def define_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=(
            sys.argv[0]
            if running_as_pyinstaller_executable()
            else f"python -m {__package__}"
        ),
        description="A command-line interface for playing Love Letter."
        " Allows multi-player games over the internet.",
    )
    parser.add_argument(
        "--client-logs",
        action="store_true",
        dest="show_client_logs",
        help="Show client logs while running: output them to stderr"
        " instead of the default file.",
    )
    parser.add_argument(
        "--server-logs",
        action="store_true",
        dest="show_server_logs",
        help="Show server logs while running."
        " Tries to open a new console window for them,"
        " otherwise outputs them to the stderr of the main process (the client).",
    )
    parser.add_argument(
        "--logging",
        "-l",
        type=logging_level,
        default=logging.INFO,
        dest="logging_level",
        help="Logging level (either a name or a numeric value). Default: WARNING",
    )
    parser.add_argument(
        "--version",
        dest="show_version",
        action="store_true",
        help="Show the version and exit.",
    )
    return parser


if __name__ == "__main__":
    multiprocessing.freeze_support()
    args = vars(define_cli().parse_args())
    if args.pop("show_version"):
        show_version()
    else:
        main(**args)
