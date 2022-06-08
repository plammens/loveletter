import shutil
import textwrap
import traceback

import valid8
from multimethod import multimethod

from loveletter_multiplayer import RemoteException


def printable_width() -> int:
    width, _ = shutil.get_terminal_size(fallback=(120, 0))
    width -= 2  # leave some margin for safety (avoid ugly wrapping)
    return width


@valid8.validate_arg("filler", valid8.validation_lib.length_between(1, 1))
def print_header(text: str, filler: str = "-"):
    print()
    width = printable_width()
    print(format(f" {text} ", f"{filler}^{width - 1}"), end="\n\n")


@valid8.validate_arg("line", lambda s: "\n" not in s)
def print_centered(line: str):
    print(format(line, f"^{printable_width()}"))


@multimethod
def print_exception(exception: BaseException):
    text = "\n".join(traceback.format_exception_only(type(exception), exception))
    return _gcd_print_exception(text)


@print_exception.register
def print_exception(exception: RemoteException):
    text = f"{exception.exc_type.__name__}: {exception.exc_message}"
    return _gcd_print_exception(text)


def _gcd_print_exception(text: str):
    text = textwrap.indent(text, prefix=" " * 4 + "!!! ")
    print(text, end="\n\n")


def pluralize(word: str, count: int) -> str:
    """Pluralize (or not) a word as appropriate given a count."""
    return word if abs(count) == 1 else f"{word}s"
