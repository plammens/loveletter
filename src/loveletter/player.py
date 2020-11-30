import typing
from typing import Sequence

from loveletter.cards import Card

if typing.TYPE_CHECKING:
    from loveletter.game import Game


class Player:
    class Hand:
        card: Card

    game: "Game"
    alive: bool
    hand: Hand
    cards_played: Sequence[Card]

    def __init__(self, game: "Game"):
        self.game = game
