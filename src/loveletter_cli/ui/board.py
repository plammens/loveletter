import shutil
import textwrap
from typing import Sequence

import more_itertools
import numpy as np

from loveletter.cards import Card, CardType
from loveletter.roundplayer import RoundPlayer
from loveletter_multiplayer import RemoteGameShadowCopy


ROW_TO_COL_RATIO = 2.8  #: approximate terminal character aspect ratio
CARD_ASPECT = 3 / 5  #: card aspect ratio


def draw_game(game: RemoteGameShadowCopy):
    game_round = game.current_round
    you = game_round.players[game.client_player_id]
    width, _ = shutil.get_terminal_size(fallback=(99, 0))
    center_fmt = f"^{width}"

    def get_player(offset: int) -> RoundPlayer:
        players = game_round.players
        return players[(you.id + offset) % len(players)]

    def cards_discarded_string(p: RoundPlayer) -> str:
        return (
            f"cards discarded: [{', '.join(f'({c.value})' for c in p.discarded_cards)}]"
        )

    def username(p: RoundPlayer) -> str:
        name = game.players[p.id].username
        if game_round.current_player is p:
            return f">>> {name} <<<"
        elif not p.alive:
            return f"💀 {name} 💀"
        else:
            return name

    # opposite opponent (at least one)
    opposite = get_player(offset=min(2, game_round.num_players - 1))
    sprites = [card_back_sprite(char="#")] * len(opposite.hand)
    print_char_array(_horizontal_join(sprites), align="^", width=width)
    print(" " * width)
    print(format(username(opposite), center_fmt))
    print(format(cards_discarded_string(opposite), center_fmt))
    print(" " * width)

    # print left and maybe right opponent(s):
    if game_round.num_players >= 3:
        center_cards = _empty_rectangle(2 * 5, width)
        center_footer = _empty_rectangle(2, width)

        # left opponent
        left = get_player(1)
        sprites = [horizontal_card_back_sprite(char="\\")] * len(left.hand)
        cards = _vertical_join(sprites)
        _embed(center_cards, cards, col=2, vcenter=True)
        _write_string(center_footer, username(left), row=0, align="<")
        _write_string(center_footer, cards_discarded_string(left), row=1, align="<")

        # right opponent
        if game_round.num_players == 4:
            right = get_player(3)
            sprites = [horizontal_card_back_sprite(char="/")] * len(right.hand)
            cards = _vertical_join(sprites)
            _embed(center_cards, cards, col=-2, vcenter=True)
            _write_string(center_footer, username(right), row=0, align=">")
            _write_string(
                center_footer, cards_discarded_string(right), row=1, align=">"
            )

        center_block = _vertical_join([center_cards, center_footer], sep_lines=1)
        print_char_array(center_block)
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
    margin: int = 2,
) -> None:
    string_width = arr.shape[1] - 2 * margin

    chars = _char_array(format(s, f"{align}{string_width}"))
    idx = (row, slice(margin, -margin))
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
    if not arrays:
        return _empty_rectangle(0, 0)
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
