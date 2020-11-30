import typing
from typing import Sequence

from loveletter.cards import Card

if typing.TYPE_CHECKING:
    from loveletter.game import Game


class Player:
    game: Game
    alive: bool
    card: Card
    cards_played: Sequence[Card]
