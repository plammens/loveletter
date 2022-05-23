import enum
import functools
import shutil
import textwrap
import traceback
from typing import (
    Callable,
    Tuple,
    Type,
    TypeVar,
)

import more_itertools
import valid8
from aioconsole import ainput
from multimethod import multimethod

from loveletter_multiplayer import RemoteException


def printable_width() -> int:
    width, _ = shutil.get_terminal_size(fallback=(100, 0))
    width -= 2  # leave some margin for safety (avoid ugly wrapping)
    return width


@valid8.validate_arg("filler", valid8.validation_lib.length_between(1, 1))
def print_header(text: str, filler: str = "-"):
    print()
    width = printable_width()
    print(format(f" {text} ", f"{filler}^{width - 1}"), end="\n\n")


T = TypeVar("T")
_DEFAULT = object()


def ask_valid_input(*args, **kwargs) -> T:
    error_message, parser, prompt, validation_errors = _ask_valid_input_parse_args(
        *args, **kwargs
    )

    while True:
        choice = input(prompt).strip()
        try:
            return parser(choice)
        except valid8.ValidationError as exc:
            print(error_message.format(choice=choice, error=exc.get_help_msg()))
        except validation_errors as exc:
            print(error_message.format(choice=choice, error=exc))


def _ask_valid_input_parse_args(
    prompt: str,
    parser: Callable[[str], T] = None,
    default: T = _DEFAULT,
    choices: enum.EnumMeta = None,
    error_message: str = "Not valid: {choice!r} ({error})",
    validation_errors: Tuple[Type[Exception]] = (ValueError,),
):
    """
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
    """
    if not prompt.endswith(" "):
        prompt += " "

    if choices is not None:
        names = list(choices.__members__.keys())
        single_case = all(map(str.islower, names)) or all(map(str.isupper, names))
        prompt += f"[{' | '.join(names)}] "

        def parser(s: str) -> choices:
            if single_case or s.islower():
                case_fold = True
                s = s.casefold()
            else:
                case_fold = False
                print("(interpreted case-*sensitively*)")

            normalized_members = (
                {
                    name.casefold(): member
                    for name, member in choices.__members__.items()
                }
                if case_fold
                else choices.__members__
            )

            try:
                return normalized_members[s]  # complete match
            except KeyError:
                # try with a partial match
                matches = {
                    name: member
                    for name, member in normalized_members.items()
                    if name.startswith(s)
                }
                return more_itertools.one(
                    matches.values(),
                    too_long=ValueError(
                        f"Ambiguous choice: which of {set(matches)} did you mean?"
                    ),
                    too_short=ValueError(
                        f"Not a valid choice: {s}; valid choices: {names}"
                    ),
                )

        validation_errors = (ValueError,)
        error_message = "{error}"

    if parser is None:
        parser = lambda x: x  # noqa

    if default is not _DEFAULT:
        default_formatted = default.name if isinstance(default, enum.Enum) else default
        prompt += f"(default: {default_formatted}) "

        @functools.wraps(parser)
        def parser(s: str, wrapped=parser) -> T:
            return default if not s else wrapped(s)

    prompt = _decorate_prompt(prompt)

    return error_message, parser, prompt, validation_errors


def _decorate_prompt(prompt: str) -> str:
    printable_width()
    text = f"? {prompt}"
    lines = textwrap.wrap(text, width=110, subsequent_indent="... " + " " * 4)
    lines.append("> ")
    return "\n".join(lines)


ask_valid_input.__doc__ = f"""
Ask for user input until it satisfies a given validator.

{_ask_valid_input_parse_args.__doc__}

:returns: The user's choice, once it's valid.
"""


async def async_ask_valid_input(*args, **kwargs):
    """Asynchronous version of :func:`ask_valid_input`."""
    error_message, parser, prompt, validation_errors = _ask_valid_input_parse_args(
        *args, **kwargs
    )

    while True:
        choice = (await ainput(prompt)).strip()
        try:
            return parser(choice)
        except validation_errors as exc:
            print(error_message.format(choice=choice, error=exc))


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


async def pause() -> None:
    await ainput("Enter something to continue... ")


def pluralize(word: str, count: int) -> str:
    """Pluralize (or not) a word as appropriate given a count."""
    return word if abs(count) == 1 else f"{word}s"
