import collections.abc
import contextlib
from typing import Iterator, List, Optional, TYPE_CHECKING, Tuple

import valid8

import loveletter.move
from loveletter.cards import Card, CardType, MoveStepGenerator
from loveletter.utils.misc import minirepr

if TYPE_CHECKING:
    from loveletter.round import Round


class RoundPlayer:
    """
    Represents a single player bound to one specific round.

    RoundPlayer objects are created every time a new Round object is instantiated, and
    they are no longer used once the round ends. Their lifecycle is bound to the
    lifecycle of the Round object; they're essentially owned by it.

    They do *not* represent a physical player of the overall Game, although each
    RoundPlayer is bound to one.

    Could have been a nested class of Round, but it has been extracted to avoid
    excessive nesting and classes in the Round code.
    """

    class Hand(collections.abc.Collection):
        def __init__(self):
            self._cards = []
            self._playing: Optional[Card] = None  # card currently being played

        # fmt: off
        def __len__(self) -> int: return len(self._cards)
        def __iter__(self) -> Iterator[Card]: return iter(self._cards)
        def __contains__(self, x: object) -> bool: return x in self._cards
        # fmt: on

        @property
        def card(self) -> Optional[Card]:
            return self._cards[0] if self._cards else None

        def __repr__(self):
            return f"<Hand of {self._cards}>"

        def add(self, card: Card):
            """Add a card to the hand"""
            valid8.validate("player.hand", self._cards, max_len=1)
            self._cards.append(card)

        def replace(self, card: Card):
            """Replace the current (only) card in the hand; return the old card"""
            valid8.validate(
                "hand",
                self._cards,
                length=1,
                help_msg="Can't replace hand with more than one card",
            )
            old, self._cards[0] = self._cards[0], card
            return old

        @contextlib.contextmanager
        def _stage_card_for_playing(self, card: "Card"):
            # set card aside in temporary holding area:
            idx = self._cards.index(card)
            self._playing = self._cards.pop(idx)
            # noinspection PyBroadException
            try:
                yield
            except:
                # Something happened; restore hand
                self._cards.insert(idx, card)
                raise
            else:
                # Move completed successfully
                pass
            finally:
                # Flush staging area
                self._playing = None

    round: "Round"
    hand: Hand
    discarded_cards: List[Card]
    immune: bool

    def __init__(self, round: "Round", player_id: int):
        self.round = round
        self.id = player_id
        self._alive = True
        self.hand = self.Hand()
        self.discarded_cards = []
        self.immune = False

    @property
    def alive(self) -> bool:
        return self._alive

    def __repr__(self):
        return f"<RoundPlayer {self.id} of {minirepr(self.round)}>"

    def __str__(self):
        return f"player-{self.id}"

    def give(self, card: Card):
        """Give this player a card; alias for hand.add"""
        self.hand.add(card)

    def play_card(self, card: Card) -> MoveStepGenerator:
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
                # tentatively remove card from hand; only commit if move terminates OK
                with self.hand._stage_card_for_playing(card):  # noqa
                    self.hand.card.check_move(self, card)  # does other card approve?
                    results = yield from card.play(self)
                results += self._discard_actions(card)
                return results
        except (loveletter.move.CancelMove, GeneratorExit):
            # Exception was injected to signal cancelling
            return

    def play_type(self, card_type: CardType) -> MoveStepGenerator:
        """Shortcut to play the first card in the hand of a given type"""
        with valid8.validation("card_type", card_type, help_msg="Not in hand"):
            for card in self.hand:
                if CardType(card) == card_type:
                    return self.play_card(card)
            else:
                raise LookupError(card_type)

    @valid8.validate_arg("self", alive.fget, help_msg="Can't eliminate dead player")
    def eliminate(self):
        self._alive = False
        for card in self.hand._cards[::-1]:
            self.discard_card(card)

    def discard_card(self, card: Card) -> Tuple[loveletter.move.MoveResult, ...]:
        valid8.validate("card", card, is_in=self.hand)
        # noinspection PyProtectedMember
        self.hand._cards.remove(card)
        return self._discard_actions(card)

    def _discard_actions(self, card: Card) -> Tuple[loveletter.move.MoveResult, ...]:
        self.round.discard_pile.place(card)
        self.discarded_cards.append(card)
        results = card.discard_effects(self)
        return results
