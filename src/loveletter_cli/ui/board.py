import functools
import itertools
import math
import textwrap
from typing import Optional, Sequence

import more_itertools
import numpy as np

from loveletter.cardpile import Deck, STANDARD_DECK_COUNTS
from loveletter.cards import Card, CardType
from loveletter.roundplayer import RoundPlayer
from loveletter_multiplayer import RemoteGameShadowCopy
from .misc import pluralize, printable_width


COLS_PER_ROW_RATIO = 2.8  #: approximate terminal character aspect ratio
CARD_ASPECT = 3 / 5  #: card aspect ratio
DEFAULT_CARD_BACK_SIZE = 8


def draw_game(game: RemoteGameShadowCopy) -> None:
    assert game.started
    game_round = game.current_round
    you = game.client_player
    board_cols = printable_width()
    center_fmt = f"^{board_cols}"

    def get_player(offset: int) -> RoundPlayer:
        players = game_round.players
        return players[(you.id + offset) % len(players)]

    def cards_discarded_string(p) -> str:
        p = game.get_player(p)
        return (
            f"cards played/discarded: "
            f"[{', '.join(f'({c.value})' for c in p.discarded_cards)}]"
        )

    def username(p) -> str:
        p = game.get_player(p)
        name = f"{p.username} (you)" if p is you else p.username
        if game_round.current_player is p:
            return f">>> {name} <<<"
        elif not p.alive:
            return f"💀 {name} 💀"
        elif p.immune:
            return f"🛡️ {name} 🛡️"
        else:
            return name

    def print_blank_line():
        print(" " * board_cols)

    print_blank_line()
    print_blank_line()

    # opposite opponent (at least one)
    opposite = get_player(offset=min(2, game_round.num_players - 1))
    sprites = [card_back_sprite(char="#")] * len(opposite.hand)
    print_char_array(_horizontal_join(sprites), align="^", width=board_cols)
    print_blank_line()
    print(format(username(opposite), center_fmt))
    print(format(cards_discarded_string(opposite), center_fmt))
    print_blank_line()

    len_stack = len(game.current_round.deck.stack)
    num_set_aside = int(game.current_round.deck.set_aside is not None)
    deck_msg = (
        f"[deck: {len_stack} (+ {num_set_aside})"
        f" {pluralize('card', len_stack + num_set_aside)}]"
    )
    if game_round.num_players >= 3:
        left_right_players = [get_player(1)]
        if game_round.num_players == 4:
            left_right_players.append(get_player(3))

        # print left and maybe right opponent(s):
        center_main = _empty_canvas(
            rows=math.ceil(2 * DEFAULT_CARD_BACK_SIZE * CARD_ASPECT),
            cols=board_cols,
        )
        center_footer = _empty_canvas(rows=2, cols=board_cols)

        for player, char, col, align in zip(left_right_players, r"\/", [2, -2], "<>"):
            sprites = [horizontal_card_back_sprite(char=char)] * len(player.hand)
            cards = _vertical_join(sprites)
            _embed(center_main, cards, col=col, vcenter=True)
            _write_string(center_footer, username(player), row=0, align=align)
            _write_string(
                center_footer, cards_discarded_string(player), row=1, align=align
            )

        # join the hands strip with their footers to form a single central strip
        center_block = _vertical_join([center_main, center_footer], sep_lines=1)

        # make use of extra vertical space to make a deck sprite
        _embed(center_block, deck_sprite(game_round.deck), hcenter=True, vcenter=True)
        _write_string(center_block, deck_msg, row=-2, align="^")

        # print everything in this central strip:
        print_char_array(center_block)
    else:
        # print "economical" representation of deck to avoid increasing vertical length
        print_blank_line()
        print(format(deck_msg, center_fmt))
        print_blank_line()

    print_blank_line()

    # this client's hand
    sprites = [card_sprite(c) for c in you.hand]
    print_char_array(_horizontal_join(sprites), align="^", width=board_cols)
    print_blank_line()
    print(format(username(you), center_fmt))
    print(format(cards_discarded_string(you), center_fmt))

    print_blank_line()
    print_blank_line()


def card_sprite(card: Card, size=15) -> np.array:
    arr = _empty_card(size)
    width = arr.shape[1]

    _write_string(arr, f"({card.value})", row=2, align="<", margin=3)
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
        _write_string(arr, line, row=i, align="^", margin=description_margin)

    return arr


def card_back_sprite(size=DEFAULT_CARD_BACK_SIZE, char="#") -> np.ndarray:
    card = _empty_card(size)
    # stripy diagonal pattern:
    layer = _checkerboard(card.shape, char)
    return _underlay(card, layer)


def horizontal_card_back_sprite(size=DEFAULT_CARD_BACK_SIZE, char="/") -> np.ndarray:
    card = _empty_canvas(round(CARD_ASPECT * size), round(COLS_PER_ROW_RATIO * size))
    _frame(card)
    layer = _checkerboard(card.shape, char)
    return _underlay(card, layer)


def deck_sprite(deck: Deck) -> np.ndarray:
    max_stack_size = sum(STANDARD_DECK_COUNTS.values()) - 1
    num_card_sprites = math.ceil((len(deck.stack) / max_stack_size) * 3)

    card_size = DEFAULT_CARD_BACK_SIZE - 1
    sprite = card_back_sprite(size=card_size)

    canvas_size = np.array(sprite.shape) + (num_card_sprites - 1)
    stack_canvas = _empty_canvas(*canvas_size)
    for i in range(num_card_sprites):
        _embed(stack_canvas, sprite, row=i, col=i)

    set_aside_sprite = card_back_sprite(size=card_size, char="@")

    return _horizontal_join([stack_canvas, set_aside_sprite])


def print_char_array(array: np.ndarray, align="", width=None):
    if width is None:
        width = array.shape[1]
    fmt = f"{align}{width}"
    for row in array:
        print(format(_as_string(row), fmt))


def _checkerboard(shape, char):
    layer = _empty_canvas(*shape)
    mask = np.arange(shape[1]) % 2 == np.arange(shape[0])[:, np.newaxis] % 2
    layer[mask] = char
    return layer


def _empty_card(height: int) -> np.ndarray:
    width = round(COLS_PER_ROW_RATIO * height * CARD_ASPECT)
    arr1 = _empty_canvas(height, width)
    arr = arr1
    _frame(arr)
    return arr


def _frame(arr):
    arr[[0, -1], :] = "¯"
    arr[-1, :] = "_"
    arr[:, [0, -1]] = "|"
    for idx, corner in zip(itertools.product([0, -1], repeat=2), "⎾⏋⎿⏌"):
        arr[idx] = corner


def _write_string(
    arr: np.ndarray,
    s: str,
    row: int,
    align: str = "",
    margin: int = 2,
) -> None:
    string_width = arr.shape[1] - 2 * margin

    chars = _char_array(format(s, f"{align}{string_width}"))
    idx = (row, slice(margin, -margin))
    arr[idx] = _overlay(arr[idx], chars)


def _embed(
    canvas: np.ndarray,
    sprite: np.ndarray,
    row: int = 0,
    col: int = 0,
    hcenter=False,
    vcenter=False,
) -> None:
    board_height, board_width = canvas.shape
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
    canvas[idx] = sprite


def _overlay(base: np.ndarray, layer: np.ndarray) -> np.ndarray:
    return np.where(layer != " ", layer, base)


def _underlay(base: np.ndarray, layer: np.ndarray) -> np.ndarray:
    return np.where(base == " ", layer, base)


def _pad(sprite: np.ndarray, rows: Optional[int], cols: Optional[int]) -> np.ndarray:
    """
    Embed a given sprite (centered) into a bigger canvas of a given size.

    If rows/cols is None, it means no padding along that axis
    (its length stays the same).
    """
    rows, cols = rows or sprite.shape[0], cols or sprite.shape[1]
    canvas = _empty_canvas(rows, cols)
    _embed(canvas, sprite, hcenter=True, vcenter=True)
    return canvas


def _join(arrays: Sequence[np.ndarray], axis: int, separation: int) -> np.ndarray:
    if not arrays:
        return _empty_canvas(0, 0)

    other_axis = (axis + 1) % 2
    other_length = max(a.shape[other_axis] for a in arrays)
    joint_shape = np.roll([separation, other_length], shift=axis)
    joint = _empty_canvas(*joint_shape)

    pad_shape = dict(zip(["cols", "rows"], np.roll([other_length, None], shift=axis)))
    padder = functools.partial(_pad, **pad_shape)
    return np.concatenate(
        list(more_itertools.intersperse(joint, map(padder, arrays))),
        axis=axis,
    )


def _horizontal_join(arrays: Sequence[np.ndarray], sep_columns: int = 2) -> np.ndarray:
    return _join(arrays, axis=1, separation=sep_columns)


def _vertical_join(arrays: Sequence[np.ndarray], sep_lines=0) -> np.ndarray:
    return _join(arrays, axis=0, separation=sep_lines)


def _empty_canvas(rows, cols) -> np.ndarray:
    # TODO: refactor into _empty_canvas_adjusted
    return np.full((rows, cols), fill_value=" ", dtype="U1")


def _char_array(s: str) -> np.ndarray:
    return np.array(list(s), dtype="U1")


def _as_string(row: np.ndarray) -> str:
    return "".join(row)
