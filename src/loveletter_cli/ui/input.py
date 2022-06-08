import enum
import functools
import os
import sys
import textwrap
from typing import Callable, Tuple, Type, TypeVar

import aioconsole
import more_itertools
import valid8

from .misc import printable_width


_T = TypeVar("_T")
_DEFAULT = object()


# Define ainput() based on OS: if the OS uses the O_NONBLOCK flag, we have to
# clear it after every call to ainput() to ensure compatibility with blocking
# IO such as print() and input().
if hasattr(os, "set_blocking"):

    @functools.wraps(aioconsole.ainput)
    async def ainput(*args, **kwargs):
        result = await aioconsole.ainput(*args, **kwargs)
        os.set_blocking(sys.stdin.fileno(), True)
        return result


    @functools.wraps(aioconsole.ainput)
    async def aprint(*args, **kwargs):
        result = await aioconsole.aprint(*args, **kwargs)
        os.set_blocking(sys.stdin.fileno(), True)
        return result

else:
    ainput = aioconsole.ainput
    aprint = aioconsole.aprint


def ask_valid_input(*args, **kwargs) -> _T:
    error_message, parser, prompt, validation_errors = _ask_valid_input_parse_args(
        *args, **kwargs
    )

    while True:
        raw_input = input(prompt)
        try:
            return _parse_input(raw_input, parser, error_message, validation_errors)
        except (valid8.ValidationError, *validation_errors):
            continue


async def async_ask_valid_input(*args, **kwargs):
    """Asynchronous version of :func:`ask_valid_input`."""
    error_message, parser, prompt, validation_errors = _ask_valid_input_parse_args(
        *args, **kwargs
    )

    while True:
        raw_input = await ainput(prompt)
        try:
            return await _parse_input(
                raw_input, parser, error_message, validation_errors
            )
        except (valid8.ValidationError, *validation_errors):
            continue


def _ask_valid_input_parse_args(
    prompt: str,
    parser: Callable[[str], _T] = None,
    default: _T = _DEFAULT,
    choices: enum.EnumMeta = None,
    error_message: str = "Not valid: {choice!r} ({error})",
    validation_errors: Tuple[Type[Exception]] = (valid8.ValidationError, ValueError),
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
        def parser(s: str, wrapped=parser) -> _T:
            return default if not s else wrapped(s)

    prompt = _decorate_prompt(prompt)

    return error_message, parser, prompt, validation_errors


async def _parse_input(raw_input: str, parser, error_message, validation_errors) -> _T:
    raw_input = raw_input.strip()
    try:
        return parser(raw_input)
    except validation_errors as exc:
        if isinstance(exc, valid8.ValidationError):
            try:
                error_text = exc.get_help_msg()
            except valid8.base.HelpMsgFormattingException:
                # failsafe in case of a help message formatting error (avoid crashing)
                error_text = exc
        else:
            error_text = exc

        await aprint(error_message.format(choice=raw_input, error=error_text))
        raise


def _decorate_prompt(prompt: str) -> str:
    printable_width()
    text = f"? {prompt}"
    lines = textwrap.wrap(text, width=110, subsequent_indent="... " + " " * 4)
    lines.append("> ")
    return "\n".join(lines)


async_ask_valid_input.__doc__ = f"""
Ask for user input until it satisfies a given validator.

{_ask_valid_input_parse_args.__doc__}

:returns: The user's choice, once it's valid.
"""


async def pause() -> None:
    # Using ainput() instead of regular input() sometimes causes trouble:
    # the user has to enter twice before input is detected;
    # but the asynchronous nature is needed to ensure other events are handled in time
    # (e.g. when the connection is lost).
    # Also caused trouble on Linux and Unix regarding the O_NONBLOCK flag
    # (see #17 and #19) but this has been fixed.
    await ainput("Enter something to continue... ")
