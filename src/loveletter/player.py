import collections
from typing import Iterator, Optional, Sequence, TYPE_CHECKING

import valid8

from loveletter.cards import Card

if TYPE_CHECKING:
    from loveletter.round import Round


class Player:
    class Hand(collections.abc.Collection):
        def __init__(self):
            self._cards = []

        # fmt: off
        def __len__(self) -> int: return len(self._cards)
        def __iter__(self) -> Iterator[Card]: return iter(self._cards)
        def __contains__(self, x: object) -> bool: return x in self._cards
        # fmt: on

        @property
        def card(self) -> Optional[Card]:
            return self._cards[0] if self._cards else None

        def add(self, card: Card):
            valid8.validate("player.hand", self._cards, max_len=1)
            self._cards.append(card)

    round: "Round"
    hand: Hand
    cards_played: Sequence[Card]

    def __init__(self, round: "Round", player_id: int):
        self.round = round
        self.id = player_id
        self._alive = True
        self.hand = self.Hand()
        self.cards_played = []

    @property
    def alive(self) -> bool:
        return self._alive

    def give(self, card: Card):
        """Give this player a card; alias for hand.add"""
        self.hand.add(card)

    def eliminate(self):
        self._alive = False
