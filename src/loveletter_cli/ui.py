import enum
import functools
import textwrap
import traceback
from typing import Callable, Tuple, Type, TypeVar

from aioconsole import ainput
from multimethod import multimethod

from loveletter_multiplayer import RemoteException


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
    error_message, parser, prompt, validation_errors = _ask_valid_input_parse_args(
        choices, default, error_message, parser, prompt, validation_errors
    )

    while True:
        choice = input(prompt).strip()
        try:
            return parser(choice)
        except validation_errors as exc:
            print(error_message.format(choice=choice, error=exc))


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


def _ask_valid_input_parse_args(
    choices, default, error_message, parser, prompt, validation_errors
):
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

    return error_message, parser, prompt, validation_errors


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
