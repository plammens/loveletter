from typing import Optional, Sequence, TYPE_CHECKING

from loveletter.cards import Card

if TYPE_CHECKING:
    from loveletter.round import Round


class Player:
    class Hand:
        card: Optional[Card]

        def __init__(self):
            self.card = None

    round: "Round"
    alive: bool
    hand: Hand
    cards_played: Sequence[Card]

    def __init__(self, round: "Round", player_id: int):
        self.round = round
        self.id = player_id
        self._alive = True
        self.hand = self.Hand()
        self.cards_played = []

    @property
    def alive(self):
        return self._alive

    def eliminate(self):
        self._alive = False
