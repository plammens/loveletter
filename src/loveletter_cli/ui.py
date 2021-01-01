import enum
import functools
import shutil
import textwrap
import traceback
from typing import (
    Callable,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
)

import more_itertools
import numpy as np
from aioconsole import ainput
from multimethod import multimethod

from loveletter.cards import Card, CardType
from loveletter.roundplayer import RoundPlayer
from loveletter_multiplayer import RemoteException, RemoteGameShadowCopy


ROW_TO_COL_RATIO = 2.8  # approximate terminal character aspect ratio
CARD_ASPECT = 3 / 5

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
        prompt += f"[{' | '.join(names)}] "
        error_message += f"; valid choices: {names}"

        def parser(s: str) -> choices:
            if all(map(str.isupper, names)):
                s = s.upper()
            return choices[s]

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


def draw_game(game: RemoteGameShadowCopy):
    game_round = game.current_round
    you = game_round.players[game.client_player_id]
    width, _ = shutil.get_terminal_size()
    center_fmt = f"^{width}"

    def cards_discarded_string(p: RoundPlayer) -> str:
        return (
            f"cards discarded: [{', '.join(f'({c.value})' for c in p.discarded_cards)}]"
        )

    def username(p: RoundPlayer) -> str:
        return game.players[p.id].username

    # opposite opponent (at least one)
    opposite = game_round.get_player(you, offset=min(2, game_round.num_players - 1))
    sprites = [card_back_sprite(char="#")] * len(opposite.hand)
    print_char_array(_horizontal_join(sprites), align="^", width=width)
    print(" " * width)
    print(format(username(opposite), center_fmt))
    print(format(cards_discarded_string(opposite), center_fmt))
    print(" " * width)

    # print left and maybe right opponent(s):
    if game_round.num_players >= 3:
        center_block = _empty_rectangle(10, width)

        # left opponent
        left = game_round.get_player(you, offset=1)
        sprites = [horizontal_card_back_sprite(char="\\")] * len(left.hand)
        cards = _vertical_join(sprites)
        _embed(center_block, cards, col=1, vcenter=True)

        # right opponent
        if game_round.num_players == 4:
            right = game_round.get_player(you, offset=-1)
            sprites = [horizontal_card_back_sprite(char="/")] * len(right.hand)
            cards = _vertical_join(sprites)
            _embed(center_block, cards, col=-1, vcenter=True)

        print_char_array(center_block)
        if game_round.num_players == 3:
            print(format(f" {username(left)}", f"<{width}"))
            print(format(f" {cards_discarded_string(left)}", f"<{width}"))
        else:
            r = width - (l := round(width / 2))
            print(f"{' ' + username(left):<{l}}{username(right) + ' ':>{r}}")
            print(
                f"{' ' + cards_discarded_string(left):<{l}}"
                f"{cards_discarded_string(right) + ' ':>{r}}"
            )

        print(" " * width)

    # hand
    sprites = [card_sprite(c) for c in you.hand]
    print_char_array(_horizontal_join(sprites), align="^", width=width)
    print(" " * width)
    print(format("Your hand", center_fmt))
    print(format(cards_discarded_string(you), center_fmt))


def card_sprite(card: Card, size=15) -> np.array:
    arr = _empty_card(size)
    width = arr.shape[1]

    _write_string(arr, f"({card.value})", row=2, align="<", margins=(2, 3))
    _write_string(arr, CardType(card).name, row=2, align="^")

    min_description_start = 4
    bottom_margin = 2
    description_margin = 4
    description_end = size - bottom_margin
    lines = textwrap.wrap(
        card.description,
        width=width - 2 * description_margin,
        max_lines=description_end - min_description_start,
    )
    description_start = description_end - len(lines)
    for i, line in enumerate(lines, start=description_start):
        _write_string(arr, line, row=i, align="^", margins=(2, description_margin))

    return arr


def card_back_sprite(size=8, char="/") -> np.ndarray:
    card = _empty_card(size)
    # stripy diagonal pattern:
    layer = _checkerboard(card.shape, char)
    return _underlay(card, layer)


def horizontal_card_back_sprite(size=8, char="/") -> np.ndarray:
    card = _empty_rectangle(round(CARD_ASPECT * size), round(ROW_TO_COL_RATIO * size))
    card[:, [0, -1]] = "¦"
    card[[0, -1], :] = "_"
    layer = _checkerboard(card.shape, char)
    return _underlay(card, layer)


def print_char_array(array: np.ndarray, align="", width=None):
    if width is None:
        width = array.shape[1]
    fmt = f"{align}{width}"
    for row in array:
        print(format(_as_string(row), fmt))


def _checkerboard(shape, char):
    layer = _empty_rectangle(*shape)
    mask = np.arange(shape[1]) % 2 == np.arange(shape[0])[:, np.newaxis] % 2
    layer[mask] = char
    return layer


def _empty_card(height: int) -> np.ndarray:
    width = round(ROW_TO_COL_RATIO * height * CARD_ASPECT)
    arr = _empty_rectangle(height, width)
    arr[:, [0, -1]] = "|"
    arr[[0, -1], :] = "-"
    return arr


def _write_string(
    arr: np.ndarray,
    s: str,
    row: int,
    align: str = "",
    margins: Union[int, Tuple[int, int]] = 2,
) -> None:
    try:
        row_margin, col_margin = margins
    except TypeError:
        row_margin, col_margin = margins, round(margins * ROW_TO_COL_RATIO)
    string_width = arr.shape[1] - 2 * col_margin

    chars = _char_array(format(s, f"{align}{string_width}"))
    idx = (row, slice(col_margin, -col_margin))
    arr[idx] = _overlay(arr[idx], chars)


def _embed(
    board: np.ndarray,
    sprite: np.ndarray,
    row: int = 0,
    col: int = 0,
    hcenter=False,
    vcenter=False,
) -> None:
    board_height, board_width = board.shape
    sprite_height, sprite_width = sprite.shape

    if hcenter:
        col = round(board_width / 2 - sprite_width / 2)
    if vcenter:
        row = round(board_height / 2 - sprite_height / 2)

    row_slice = (
        slice(row, row + sprite_height)
        if row >= 0
        else slice(board_height - sprite_height + row, row)
    )
    col_slice = (
        slice(col, col + sprite_width)
        if col >= 0
        else slice(board_width - sprite_width + col, col)
    )
    idx = (row_slice, col_slice)
    board[idx] = _overlay(board[idx], sprite)


def _overlay(base: np.ndarray, layer: np.ndarray) -> np.ndarray:
    return np.where(layer != " ", layer, base)


def _underlay(base: np.ndarray, layer: np.ndarray) -> np.ndarray:
    return np.where(base == " ", layer, base)


def _horizontal_join(arrays: Sequence[np.ndarray], sep="  ") -> np.ndarray:
    rows = arrays[0].shape[0]
    assert all(a.shape[0] == rows for a in arrays)
    joint = _empty_rectangle(rows, len(sep))
    joint[:] = _char_array(sep)
    return np.hstack(list(more_itertools.intersperse(joint, arrays)))


def _vertical_join(arrays: Sequence[np.ndarray], sep_lines=0) -> np.ndarray:
    cols = arrays[0].shape[1]
    assert all(a.shape[1] == cols for a in arrays)
    joint = _empty_rectangle(sep_lines, cols)
    return np.vstack(list(more_itertools.intersperse(joint, arrays)))


def _empty_rectangle(rows, cols) -> np.ndarray:
    return np.full((rows, cols), fill_value=" ", dtype="U1")


def _char_array(s: str) -> np.ndarray:
    return np.array(list(s), dtype="U1")


def _as_string(row: np.ndarray) -> str:
    return "".join(row)
