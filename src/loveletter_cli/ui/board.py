import functools
import itertools
import math
import textwrap
from typing import Literal, Optional, Sequence, Tuple, Union

import more_itertools
import numpy as np

from loveletter.cardpile import Deck, STANDARD_DECK_COUNTS
from loveletter.cards import Card, CardType, Guard
from loveletter.round import RoundState
from loveletter.roundplayer import RoundPlayer
from loveletter_multiplayer import RemoteGameShadowCopy
from .misc import pluralize, printable_width


TRANSPARENT = "\0"  # character that indicates transparency
COLS_PER_ROW_RATIO = 2.8  #: approximate terminal character aspect ratio
CARD_ASPECT = 3 / 5  #: card aspect ratio
DEFAULT_CARD_HEIGHT = DEFAULT_CARD_SIZE = 8  #: card size in row units
DEFAULT_CARD_WIDTH = DEFAULT_CARD_HEIGHT * CARD_ASPECT


def draw_game(
    game: RemoteGameShadowCopy,
    reveal: bool = False,
    player_card_size: int = 15,
    other_card_size: int = 13,
) -> None:
    """
    Print the game board (a graphical representation of the game state) to stdout.

    :param game: The game object to represent; must be a RemoteGameShadowCopy (a client
        of a multiplayer game).
    :param reveal: Whether to reveal the cards of all players.
    :param player_card_size: Size of the client player's card sprites.
    :param other_card_size: Size of other players' card sprites, if revealing them.
        Only applies if `reveal` is ``True``; ignored otherwise.
    """
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
            f"discarded: " f"[{', '.join(f'({c.value})' for c in p.discarded_cards)}]"
        )

    def username(p) -> str:
        p = game.get_player(p)
        points = game.points[p]
        label = f" {p.username} [{points}t] "
        current = game_round.current_player
        state = game_round.state
        is_round_end = state.type == RoundState.Type.ROUND_END

        if is_round_end and p.round_player in state.winners:  # noqa
            return f"🏆 {label} 🏆"
        elif current is not None and p.id == current.id:
            return f">>> {label} <<<"
        elif not p.alive:
            return f"💀 {label} 💀"
        elif p.immune:
            return f"🛡️ {label} 🛡️"
        else:
            return label

    def print_blank_line():
        print(" " * board_cols)

    print_blank_line()
    print_blank_line()

    # number of extra rows of players (one to the left one to the right)
    extra_player_rows = math.ceil((game_round.num_players - 2) / 2)

    # opposite opponent (at least one)
    opposite = get_player(offset=extra_player_rows + 1)
    sprites = (
        [card_sprite(c, size=other_card_size) for c in opposite.hand]
        if reveal
        else [card_back_sprite(char="#")] * len(opposite.hand)
    )
    print_canvas(horizontal_join(sprites), align="^", width=board_cols)
    print_blank_line()
    print(format(username(opposite), center_fmt))
    print(format(cards_discarded_string(opposite), center_fmt))
    print_blank_line()

    len_stack = len(game.current_round.deck.stack)
    num_set_aside = int(game.current_round.deck.set_aside is not None)
    deck_msg = (
        f"["
        f"deck: {len_stack}"
        f" {pluralize('card', len_stack)}"
        f"{f' (+ {num_set_aside} out of play)' if num_set_aside else ''}"
        f"]"
    )
    if game_round.num_players <= 2:
        assert extra_player_rows == 0
        # print "economical" representation of deck to avoid increasing vertical length
        print_blank_line()
        print(format(deck_msg, center_fmt))
        print_blank_line()
    else:
        # canvases for center strip: main -> the card sprites, footer -> the labels
        # make dummy sprite to make sure we get the dimensions right
        sprite_sample = (
            card_sprite(Guard(), size=other_card_size)
            if reveal
            else card_back_sprite(orientation="sideways")
        )

        # player in first row, on the left: the offset is ``player_rows``
        # the player at the top is at offset ``player_rows + 1``
        # the player next to that (first row, on the right) is at ``player_rows + 2``
        # and so on

        row_blocks = []
        for left_offset, right_offset in itertools.zip_longest(
            range(extra_player_rows, 0, -1),
            range(extra_player_rows + 2, game_round.num_players),
        ):
            left_right_players = [get_player(left_offset)]
            if right_offset is not None:
                left_right_players.append(get_player(right_offset))

            # if reveal is True, the cards will be upright and joined horizontally,
            # otherwise they will be sideways and joined vertically
            display_rows = (1 if reveal else 2) * sprite_sample.shape[0]
            row_main = empty_canvas(rows=display_rows, cols=board_cols)
            row_footer = empty_canvas(rows=2, cols=board_cols)

            # draw the left and right players on this row
            for player, char, col, align in zip(
                left_right_players, r"\/", [2, -2], "<>"
            ):
                if reveal:
                    sprites = [
                        card_sprite(c, size=other_card_size) for c in player.hand
                    ]
                    cards = horizontal_join(sprites)
                else:
                    sideways_sprite = card_back_sprite(
                        orientation="sideways", char=char
                    )
                    sprites = [sideways_sprite] * len(player.hand)
                    cards = vertical_join(sprites)

                embed(row_main, cards, col=col, vcenter=True)
                write_string(row_footer, username(player), row=0, align=align)
                write_string(
                    row_footer, cards_discarded_string(player), row=1, align=align
                )

            # join the hands strip with their footers to form a single strip
            row_block = vertical_join([row_main, row_footer], sep_lines=1)
            row_blocks.append(row_block)

        center_block = vertical_join(row_blocks, sep_lines=2)

        # make use of extra vertical space to make a deck sprite
        deck_layer = empty_canvas(*center_block.shape)
        row_slice, _ = embed(
            deck_layer,
            deck_sprite(game_round.deck),
            hcenter=True,
            row=-1,
            vcenter=True,
        )
        write_string(deck_layer, deck_msg, row=row_slice.stop + 1, align="^")
        center_block = underlay(base=center_block, layer=deck_layer)

        # print everything in this central strip:
        print_canvas(center_block)

    print_blank_line()

    # this client's hand
    sprites = [card_sprite(c, size=player_card_size) for c in you.hand]
    print_canvas(horizontal_join(sprites), align="^", width=board_cols)
    print_blank_line()
    print(format(username(you), center_fmt))
    print(format(cards_discarded_string(you), center_fmt))

    print_blank_line()
    print_blank_line()


# ---------------------------------- canvas creation ----------------------------------


def empty_canvas(rows: Union[int, float], cols: Union[int, float]) -> np.ndarray:
    """
    Create an empty canvas of the specified dimensions.

    The canvas will be a 2D numpy array of dtype U1 (unicode strings of length 1, i.e.
    characters). The space character is considered as the "identity"/transparency/empty
    symbol.

    Each dimension is rounded to the nearest integer number of rows/cols respectively.
    """
    rows, cols = map(round, (rows, cols))
    # the empty string represents transparency, while a space is solid background
    return np.full((rows, cols), fill_value=TRANSPARENT, dtype="U1")


def empty_canvas_adjusted(
    rows: Union[int, float], cols: Union[int, float]
) -> np.ndarray:
    """
    Create an empty canvas of the specified dimensions, adjusting for a 1:1 base ratio.

    Adjusts the dimensions so the vertical length of 1 (virtual) row unit and the
    horizontal length of 1 (virtual) column unit are approximately equal,
    by increasing the number of physical columns per virtual row unit to adjust for
    the aspect ratio of physical rows/columns. The converted dimensions are passed to
    :func:`empty_canvas` and the result of that is returned.

    :param rows: Height in virtual row units (will correspond 1:1 to physical rows).
    :param cols: Height in virtual column units (will *not* correspond 1:1 to
        physical columns).
    :return: An empty canvas of the specified dimensions.
    """
    return empty_canvas(rows, COLS_PER_ROW_RATIO * cols)


# -------------------------- graphical primitives/operations --------------------------


def embed(
    canvas: np.ndarray,
    sprite: np.ndarray,
    row: int = 0,
    col: int = 0,
    hcenter=False,
    vcenter=False,
) -> Tuple[slice, slice]:
    """
    Embed a sprite at the specified position within a larger canvas.

    The sprite overwrites any previous content that was in that area previously.

    :param canvas: Canvas (rectangular character array) in which to draw the sprite.
    :param sprite: Rectangular character array to draw in the canvas.
    :param row: Row index of the top-left corner of the embedding.
    :param col: Column index of the top-left corner of the embedding.
    :param hcenter: Whether to center horizontally; if so, `row` is considered
        as an offset from the center.
    :param vcenter: Whether to center vertically; if so, `col` is considered
        as an offset from the center.

    :return: The bounding box of the drawn sprite as (high, low) row slice and
        (left, right) column slice.
    """
    board_height, board_width = canvas.shape
    sprite_height, sprite_width = sprite.shape

    if hcenter:
        col = round(board_width / 2 - sprite_width / 2) + col
    if vcenter:
        row = round(board_height / 2 - sprite_height / 2) + row

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

    return row_slice, col_slice


def overlay(base: np.ndarray, layer: np.ndarray) -> np.ndarray:
    """
    Overlay the contents of a layer on top of a base layer of the same dimensions.

    Any nulls (empty string, representing transparency) in the overlaid layer will allow
    to "see through" to the base layer;
    i.e. nulls in the top layer will be replaced with whatever is below them in the
    base layer.
    This is a pure function.

    :returns: The result of overlaying `layer` on top of `base`.
    """
    return np.where(layer != TRANSPARENT, layer, base)


def underlay(base: np.ndarray, layer: np.ndarray) -> np.ndarray:
    """
    Underlay the contents of a layer below a base layer of the same dimensions.

    Any blanks in the base layer will allow to "see through" to the underlaid layer;
    i.e. blanks in the base layer will be replaced with whatever is below them in the
    underlaid layer. This is a pure function.

    :returns: The result of underlaying `layer` below `base`.
    """
    return np.where(base == TRANSPARENT, layer, base)


def pad(sprite: np.ndarray, rows: Optional[int], cols: Optional[int]) -> np.ndarray:
    """
    Embed a given sprite (centered) into a bigger blank canvas of a given size.

    If rows/cols is None, it means no padding along that axis (its length stays the
    same as in the original sprite).

    :returns: The result of growing the margins of `sprite` up to a target canvas size.
    """
    rows, cols = rows or sprite.shape[0], cols or sprite.shape[1]
    canvas = empty_canvas(rows, cols)
    embed(canvas, sprite, hcenter=True, vcenter=True)
    return canvas


def _join(arrays: Sequence[np.ndarray], axis: int, separation: int) -> np.ndarray:
    """
    Join a sequence of drawings along the given axis with the given separation.

    Each drawing is padded along the other axis with :func:`pad` to ensure that they
    all have the same width (axis=0) or height (axis=1) so that they can be
    concatenated together.

    :param arrays: Sequence of arrays to join.
    :param axis: Axis along which to join - 0: rows, 1: columns.
    :param separation: Number of blank rows (axis=0) or columns (axis=1) separating
        each drawing in `arrays` in the final result.
    :return: A new array consisting of the concatenation of `arrays` with the
        given separation between each.
    """
    if not arrays:
        return empty_canvas(0, 0)

    other_axis = (axis + 1) % 2
    other_length = max(a.shape[other_axis] for a in arrays)
    joint_shape = np.roll([separation, other_length], shift=axis)
    joint = empty_canvas(*joint_shape)

    pad_shape = dict(zip(["cols", "rows"], np.roll([other_length, None], shift=axis)))
    padder = functools.partial(pad, **pad_shape)
    return np.concatenate(
        list(more_itertools.intersperse(joint, map(padder, arrays))),
        axis=axis,
    )


def horizontal_join(arrays: Sequence[np.ndarray], sep_columns: int = 2) -> np.ndarray:
    """Join a sequence of sprites horizontally; see :func:`_join`."""
    return _join(arrays, axis=1, separation=sep_columns)


def vertical_join(arrays: Sequence[np.ndarray], sep_lines: int = 0) -> np.ndarray:
    """Join a sequence of sprites vertically; see :func:`_join`."""
    return _join(arrays, axis=0, separation=sep_lines)


# ------------------------------------- patterns --------------------------------------


def draw_checkerboard(canvas: np.ndarray, char: str) -> None:
    """Draw a checkerboard pattern with the given character on the given canvas."""
    nrows, ncols = canvas.shape
    mask = np.arange(ncols) % 2 == np.arange(nrows)[:, np.newaxis] % 2
    canvas[mask] = char


def draw_frame(canvas: np.ndarray) -> None:
    """Draw a frame along the perimeter of the canvas, in-place."""
    canvas[[0, -1], :] = "¯"
    canvas[-1, :] = "_"
    canvas[:, [0, -1]] = "|"
    for idx, corner in zip(itertools.product([0, -1], repeat=2), "⎾⏋⎿⏌"):
        canvas[idx] = corner


# -------------------------------------- sprites --------------------------------------


def _empty_card_canvas(
    height: int, orientation: Literal["upright", "sideways"] = "upright"
):
    """
    Make an rectangle of the size of a card.

    :param height: Height in (virtual) row units of the upright card.
    :param orientation: Orientation of the card: upright (vert.) or sideways (horiz.).
    :return: An empty canvas for a card of the given size in the given orientation.
    """
    assert orientation in ("upright", "sideways")
    shape = (height, height * CARD_ASPECT)
    if orientation == "sideways":
        shape = shape[::-1]
    return empty_canvas_adjusted(*shape)


def _empty_card(
    height: int, orientation: Literal["upright", "sideways"] = "upright"
) -> np.ndarray:
    """Make an empty card sprite (a drawn rectangle of the appropriate size)."""
    arr = _empty_card_canvas(height, orientation)
    draw_frame(arr)
    return arr


def card_sprite(card: Card, size=DEFAULT_CARD_SIZE) -> np.array:
    """Make a face-up card sprite for a given card object."""
    arr = _empty_card(size)
    width = arr.shape[1]

    write_string(arr, f"({card.value})", row=2, align="<", margin=3)
    write_string(arr, CardType(card).name, row=2, align="^")

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
        write_string(arr, line, row=i, align="^", margin=description_margin)

    return arr


def card_back_sprite(
    size=DEFAULT_CARD_SIZE,
    orientation: Literal["upright", "sideways"] = "upright",
    char="#",
) -> np.ndarray:
    """Make a face-down card sprite."""
    card = _empty_card(size, orientation)
    layer = _empty_card_canvas(size, orientation)
    draw_checkerboard(layer, char)
    return underlay(card, layer)


def deck_sprite(deck: Deck) -> np.ndarray:
    """Make a sprite illustrating the state of the deck."""
    max_stack_size = sum(STANDARD_DECK_COUNTS.values()) - 1
    num_card_sprites = math.ceil((len(deck.stack) / max_stack_size) * 3)

    card_size = DEFAULT_CARD_SIZE - 1
    sprite = card_back_sprite(size=card_size)

    canvas_size = np.array(sprite.shape) + (num_card_sprites - 1)
    stack_canvas = empty_canvas(*canvas_size)
    for i in range(num_card_sprites):
        embed(stack_canvas, sprite, row=i, col=i)

    if deck.set_aside is not None:
        set_aside_sprite = card_back_sprite(size=card_size, char="@")
        return horizontal_join([stack_canvas, set_aside_sprite])
    else:
        return stack_canvas


# --------------------------------- string utilities ----------------------------------


def as_char_array(s: str) -> np.ndarray:
    """Make a 1D character array representing the given string."""
    return np.array(list(s), dtype="U1")


def as_string(row: np.ndarray) -> str:
    """Convert a 1D character array into a string."""
    return "".join(np.where(row == TRANSPARENT, " ", row))


def write_string(
    canvas: np.ndarray,
    s: str,
    row: int,
    align: str = "",
    margin: int = 2,
) -> None:
    """
    Inscribe the given single-line string into a row of a given canvas, in-place.

    :param canvas: Canvas in which to write the string.
    :param s: String to inscribe.
    :param row: Index of the row in which to write the string.
    :param align: Horizontal alignment of the string as recognized by .format() syntax.
    :param margin: (Minimum) left and right margin to leave when embedding the string.
    """
    string_width = canvas.shape[1] - 2 * margin
    chars = as_char_array(format(s, f"{TRANSPARENT}{align}{string_width}"))
    idx = (row, slice(margin, -margin))
    canvas[idx] = overlay(canvas[idx], chars)


# ------------------------------------- utilities -------------------------------------


def print_canvas(canvas: np.ndarray, align="", width: Optional[int] = None) -> None:
    """
    Print the given canvas to stdout.

    :param canvas: Canvas to print.
    :param width: Width to which to print each row of the canvas (useful for
        left and/or right padding). The default is the width of the canvas itself.
    :param align: Alignment (as understood by .format()) of each row of the canvas
        within the wider printed row (useful together with `width`).
    """
    if width is None:
        width = canvas.shape[1]
    fmt = f"{align}{width}"
    for row in canvas:
        print(format(as_string(row), fmt))
