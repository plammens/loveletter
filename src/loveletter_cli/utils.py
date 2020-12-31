import enum
import functools
import ipaddress
import shutil
import socket
from functools import lru_cache
from typing import Callable, Tuple, Type, TypeVar

import valid8


T = TypeVar("T")


_DEFAULT = object()


def ask_valid_input(
    prompt: str,
    parser: Callable[[str], T] = None,
    default: T = _DEFAULT,
    choices: enum.EnumMeta = None,
    error_message: str = "Not valid: {choice!r} ({error})",
    validation_errors: Tuple[Type[Exception]] = (ValueError,),
) -> T:
    """
    Ask for user input until it satisfies a given validator.

    :param prompt: Prompt string to use with input().
    :param parser: A function that takes the string input and parses it to the
         corresponding object, or raises an exception if it's not valid.
    :param default: If given, return this default if the user doesn't input anything,
         skipping the call to ``parser``.
    :param choices: If given, make the user choose from the names of the members of
        the given enum. The prompt and error message will be modified to include the
        allowed values. Parameters `parser` and `validation_errors` will be ignored.
    :param error_message: A .format() template string for an error message if the user
        inputs something invalid. Valid keys:
         - `choice`: the user's choice (a string).
         - `error`: the exception raised by ``parser``.
    :param validation_errors: A tuple of exception types to be caught when calling the
        parser and considered as validation errors.

    :returns: The user's choice, once it's valid.
    """
    if not prompt.endswith(" "):
        prompt += " "

    if choices is not None:
        names = list(choices.__members__.keys())
        prompt += f"[{' | '.join(names)}] "
        error_message += f"; valid choices: {names}"

        def parser(s: str) -> choices:
            return choices[s.upper()]

        validation_errors = (KeyError,)

    if parser is None:
        parser = lambda x: x  # noqa

    if default is not _DEFAULT:
        default_formatted = default.name if isinstance(default, enum.Enum) else default
        prompt += f"(default: {default_formatted}) "

        @functools.wraps(parser)
        def parser(s: str, wrapped=parser) -> T:
            return default if not s else wrapped(s)

    while True:
        choice = input(prompt).strip()
        try:
            return parser(choice)
        except validation_errors as exc:
            print(error_message.format(choice=choice, error=exc))


@lru_cache
def get_public_ip() -> ipaddress.IPv4Address:
    import urllib.request, urllib.error

    try:
        ip = urllib.request.urlopen("http://ident.me").read().decode()
    except urllib.error.URLError:
        raise RuntimeError("Couldn't get public IP") from None

    return ipaddress.ip_address(ip)


def get_local_ip() -> ipaddress.IPv4Address:
    return ipaddress.ip_address(socket.gethostbyname(socket.getfqdn()))


def is_valid_ipv4(ip: str) -> bool:
    try:
        socket.inet_pton(socket.AF_INET, ip)
    except OSError:
        return False
    else:
        return True


@valid8.validate_arg("filler", valid8.validation_lib.length_between(1, 1))
def print_header(text: str, filler: str = "-"):
    width, _ = shutil.get_terminal_size()
    print(format(f" {text} ", f"{filler}^{width - 1}"), end="\n\n")