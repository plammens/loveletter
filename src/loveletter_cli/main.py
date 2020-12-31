import asyncio
import logging
import socket

from loveletter_cli.session import (
    CommandLineSession,
    HostVisibility,
    PlayMode,
    UserInfo,
)
from loveletter_cli.utils import (
    ask_valid_input,
    get_local_ip,
    get_public_ip,
    print_header,
)
from loveletter_multiplayer import DEFAULT_PORT, MAX_PORT, valid8
from loveletter_multiplayer.logging import setup_logging
from loveletter_multiplayer.utils import Address


def main(logging_level: int = logging.INFO):
    setup_logging(logging_level)

    print_header("Welcome to Love Letter (CLI)!", filler="~")

    user = ask_user()
    session = CommandLineSession(user)
    print(f"Welcome, {user.username}!")

    mode = ask_play_mode()
    print()

    runners = {PlayMode.JOIN: join_game, PlayMode.HOST: host_game}
    return runners[mode](session)


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


def host_game(session: CommandLineSession):
    print_header("Hosting a game")
    mode = ask_valid_input(
        "Choose the server's visibility:",
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
            addresses["local"],
        )  # allow either localhost or local net.
    print(f"Your address: {' | '.join(f'{v} ({k})' for k, v in addresses.items())}")
    port = ask_port_for_hosting()
    print()
    asyncio.run(session.host_game(hosts, port))


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


def join_game(session: CommandLineSession):
    print_header("Joining game")
    address = ask_address_for_joining()
    print()
    asyncio.run(session.join_game(*address))


def ask_address_for_joining() -> Address:
    def parser(s: str) -> Address:
        host, port = s.split(":")
        with valid8.validation("host", host, help_msg="Invalid host"):
            host = socket.gethostbyname(host)
        port = int(port)
        valid8.validate("port", port, min_value=1, max_value=1 << 16, max_strict=True)
        return Address(host, port)

    return ask_valid_input(
        prompt='Enter the server\'s address: (format: "<host>:<port>")', parser=parser
    )


# ------------------------------------- utilities -------------------------------------
