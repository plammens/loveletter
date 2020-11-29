from typing import Sequence

from loveletter.cards import Card


class Player:
    alive: bool
    card: Card
    cards_played: Sequence[Card]
