import shutil
import textwrap
import traceback

import valid8
from aioconsole import aprint
from multimethod import multimethod

from loveletter_multiplayer import RemoteException


def printable_width() -> int:
    width, _ = shutil.get_terminal_size(fallback=(120, 0))
    width -= 2  # leave some margin for safety (avoid ugly wrapping)
    return width


@valid8.validate_arg("filler", valid8.validation_lib.length_between(1, 1))
async def print_header(text: str, filler: str = "-"):
    await aprint()
    width = printable_width()
    await aprint(format(f" {text} ", f"{filler}^{width - 1}"), end="\n\n")


@valid8.validate_arg("line", lambda s: "\n" not in s)
async def print_centered(line: str):
    await aprint(format(line, f"^{printable_width()}"))


@multimethod
async def print_exception(exception: BaseException):
    text = "\n".join(traceback.format_exception_only(type(exception), exception))
    return await _gcd_print_exception(text)


@print_exception.register
async def print_exception(exception: RemoteException):
    text = f"{exception.exc_type.__name__}: {exception.exc_message}"
    return await _gcd_print_exception(text)


async def _gcd_print_exception(text: str):
    text = textwrap.indent(text, prefix=" " * 4 + "!!! ")
    await aprint(text, end="\n\n")


def pluralize(word: str, count: int) -> str:
    """Pluralize (or not) a word as appropriate given a count."""
    return word if abs(count) == 1 else f"{word}s"
