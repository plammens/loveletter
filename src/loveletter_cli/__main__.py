import argparse
import asyncio
import enum
import functools
import logging
import multiprocessing
import socket
import time
import traceback

from loveletter_cli.data import HostVisibility, PlayMode, UserInfo
from loveletter_cli.exceptions import Restart
from loveletter_cli.session import (
    GuestCLISession,
    HostCLISession,
)
from loveletter_cli.ui import ask_valid_input, print_exception, print_header
from loveletter_cli.utils import (
    get_local_ip,
    get_public_ip,
)
from loveletter_multiplayer import DEFAULT_PORT, MAX_PORT, valid8
from loveletter_multiplayer.logging import setup_logging
from loveletter_multiplayer.utils import Address


class UnhandledExceptionOptions(enum.Enum):
    RESTART = enum.auto()
    QUIT = enum.auto()


def main(
    show_client_logs: bool, show_server_logs: bool, logging_level: int = logging.INFO
):
    setup_logging(logging_level)
    if not show_client_logs:
        logging.disable()

    runners = {
        PlayMode.JOIN: join_game,
        PlayMode.HOST: functools.partial(host_game, show_server_logs=show_server_logs),
    }
    while True:
        try:
            print_header("Welcome to Love Letter (CLI)!", filler="~")

            user = ask_user()
            print(f"Welcome, {user.username}!")

            mode = ask_play_mode()
            print()
            return runners[mode](user)
        except Restart:
            continue
        except Exception as e:
            traceback.print_exc()
            time.sleep(0.2)
            print("Unhandled exception:")
            print_exception(e)
            time.sleep(0.2)
            choice = ask_valid_input(
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


def ask_user():
    username = input("Enter your username: ").strip()
    user = UserInfo(username)
    return user


def ask_play_mode() -> PlayMode:
    prompt = f"Would you like to host a game or join an existing one? "
    error_message = "Not a valid mode: {choice!r}"
    return ask_valid_input(
        prompt=prompt,
        choices=PlayMode,
        error_message=error_message,
        validation_errors=(KeyError,),
    )


def host_game(user: UserInfo, show_server_logs: bool):
    print_header("Hosting a game")
    mode = ask_valid_input(
        "Choose the server_addresses's visibility:",
        choices=HostVisibility,
        default=HostVisibility.PUBLIC,
    )
    addresses = {"local": get_local_ip()}
    if mode == HostVisibility.PUBLIC:
        addresses["public"] = get_public_ip()
        hosts = ("",)
    else:
        hosts = (
            "127.0.0.1",
            str(addresses["local"]),
        )  # allow either localhost or local net.
    print(f"Your address: {' | '.join(f'{v} ({k})' for k, v in addresses.items())}")
    port = ask_port_for_hosting()

    session = HostCLISession(user, hosts, port, show_server_logs=show_server_logs)
    asyncio.run(session.manage())


def ask_port_for_hosting() -> int:
    def parser(s: str) -> int:
        port = int(s)
        if not (socket.IPPORT_USERRESERVED <= port <= MAX_PORT):
            raise ValueError(port)
        return port

    return ask_valid_input(
        prompt=(
            f"Choose a port number >= {socket.IPPORT_USERRESERVED}, <= {MAX_PORT}:"
        ),
        parser=parser,
        default=DEFAULT_PORT,
        error_message="Not a valid, non-reserved, port: {choice}",
    )


def join_game(user: UserInfo):
    print_header("Joining game")
    address = ask_address_for_joining()
    session = GuestCLISession(user, address)
    asyncio.run(session.manage())


def ask_address_for_joining() -> Address:
    def parser(s: str) -> Address:
        host, port = s.split(":")
        with valid8.validation("host", host, help_msg="Invalid host"):
            host = socket.gethostbyname(host)
        port = int(port)
        valid8.validate("port", port, min_value=1, max_value=1 << 16, max_strict=True)
        return Address(host, port)

    return ask_valid_input(
        prompt='Enter the server_addresses\'s address: (format: "<host>:<port>")',
        parser=parser,
    )


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
    parser = argparse.ArgumentParser(prog="python -m loveletter_cli")
    parser.add_argument(
        "--client-logs",
        action="store_true",
        dest="show_client_logs",
        help="Show client logs. These are outputted to stderr.",
    )
    parser.add_argument(
        "--server-logs",
        action="store_true",
        dest="show_server_logs",
        help="Show server logs. Tries to open a new console window for them,"
        " otherwise outputs them to the stderr of the main process (the client).",
    )
    parser.add_argument(
        "--logging",
        "-l",
        type=logging_level,
        default=logging.WARNING,
        dest="logging_level",
        help="Logging level (either a name or a numeric value). Default: WARNING",
    )
    return parser


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main(**vars(define_cli().parse_args()))
