from typing import Optional, Sequence, TYPE_CHECKING

from loveletter.cards import Card

if TYPE_CHECKING:
    from loveletter.game import Game


class Player:
    class Hand:
        card: Optional[Card]

        def __init__(self):
            self.card = None

    game: "Game"
    alive: bool
    hand: Hand
    cards_played: Sequence[Card]

    def __init__(self, game: "Game", player_id: int):
        self.game = game
        self.id = player_id
        self.alive = True
        self.hand = self.Hand()
        self.cards_played = []
