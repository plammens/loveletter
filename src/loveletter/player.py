import collections
from typing import Generator, Iterator, List, Optional, TYPE_CHECKING

import valid8

from loveletter.cards import Card
from loveletter.move import CancelMove, MoveStep

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
    cards_played: List[Card]
    immune: bool

    def __init__(self, round: "Round", player_id: int):
        self.round = round
        self.id = player_id
        self._alive = True
        self.hand = self.Hand()
        self.cards_played = []
        self.immune = False

    @property
    def alive(self) -> bool:
        return self._alive

    def give(self, card: Card):
        """Give this player a card; alias for hand.add"""
        self.hand.add(card)

    def play_card(self, card: Card) -> Generator[MoveStep, MoveStep, None]:
        """
        Play a card from this player's hand.

        The details of how this generator works are explained in
        :meth:`loveletter.cards.Card.play`.

        In addition to that, this wrapper also manages updating the state of this
        player's turn. In particular, when the move is committed (by calling .close()),
        the card is removed from the player's hand and placed on the discard
        pile, and the turn is marked as completed. If the generator is exited in any
        other way (e.g. the move gets cancelled by throwing CancelMove), the turn
        gets reset to its initial state.

        :param card: Which card to play; either "left" or "right".
        :returns: A generator wrapped around ``card.play(self)``.
        """
        turn = self.round.state
        valid8.validate(
            "turn",
            turn.current_player,
            custom=lambda p: p is self,
            help_msg=f"It's not {self}'s turn",
        )
        valid8.validate(
            "card",
            card,
            is_in=self.hand,
            help_msg="Can't play a card that is not in the player's hand",
        )
        valid8.validate(
            "hand",
            self.hand,
            length=2,
            help_msg="Can't play a card with only one card in hand",
        )
        try:
            # The context manager ensures the move is completed before the round moves
            # on to the next turn
            with turn:
                yield from card.play(self)
        except CancelMove:
            # Exception was injected to signal cancelling
            return
        except GeneratorExit:
            # Move completed successfully; finish cleaning up and committing the move:
            self._discard_card(card)
        else:
            # Neither cancelled nor committed; something was sent after move.DONE
            # Raise StopIteration by just "falling off the end"
            pass

    def eliminate(self):
        assert len(self.hand) == 1
        self._discard_card(self.hand.card)
        self._alive = False

    def _discard_card(self, card: Card):
        # noinspection PyProtectedMember
        self.hand._cards.remove(card)
        self.round.discard_pile.place(card)
        self.cards_played.append(card)
