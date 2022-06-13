import abc
import collections.abc
import itertools as itt
import random
from typing import Counter, Iterator, List, Optional, Sequence, Type, TypeVar

import more_itertools as mitt

from loveletter.cards import (
    Card,
    CardType,
)

STANDARD_DECK_COUNTS: Counter[CardType] = collections.Counter(
    {
        CardType.SPY: 2,
        CardType.GUARD: 6,
        CardType.PRIEST: 2,
        CardType.BARON: 2,
        CardType.HANDMAID: 2,
        CardType.PRINCE: 2,
        CardType.CHANCELLOR: 2,
        CardType.KING: 1,
        CardType.COUNTESS: 1,
        CardType.PRINCESS: 1,
    }
)

# noinspection PyTypeChecker
_T = TypeVar("_T", bound="CardPile")


class CardPile(collections.abc.Collection, metaclass=abc.ABCMeta):
    """
    A collection of cards with a specific purpose in the game.

    Objects of this class consist of a stack of cards plus, optionally, other arbitrary
    card storage. If viewed as a collection, iterating yields all cards contained in the
    pile, first any spare cards and then the stack (from bottom to top).
    """

    def __init__(self, cards: Sequence[Card]):
        self.stack: List[Card] = list(cards)

    @classmethod
    def from_counts(cls: Type[_T], counts: Counter[CardType]) -> _T:
        """
        Create a new card pile with the given number of copies of each card.

        The cards are shuffled (the order is random).

        :param counts: A counter indicating the number of copies for each type of card
            that the card pile should have.
        :return: The new card pile.
        """
        cards = list(
            itt.chain.from_iterable(
                mitt.repeatfunc(card_type.card_class, count)
                for card_type, count in counts.items()
            )
        )
        random.shuffle(cards)
        return cls.from_cards(cards)

    @classmethod
    def from_cards(cls: Type[_T], cards) -> _T:
        return cls(cards)

    def __len__(self) -> int:
        return len(self.stack)

    def __iter__(self) -> Iterator[Card]:
        return iter(self.stack)

    def __contains__(self, x: object) -> bool:
        return x in self.stack

    def __eq__(self, o: object) -> bool:
        """Two piles are equal if their stacks (and any other cards) are equal."""
        if not isinstance(o, type(self)):
            return NotImplemented
        return self.stack == o.stack

    def __repr__(self):
        return f"{self.__class__.__name__}({self.stack})"

    @property
    def top(self) -> Optional[Card]:
        return self.stack[-1] if len(self.stack) else None

    @abc.abstractmethod
    def place(self, card: Card) -> None:
        self.stack.append(card)

    @abc.abstractmethod
    def take(self) -> Card:
        return self.stack.pop()

    def get_counts(self) -> Counter[CardType]:
        """Returns a dictionary of card type to count in the pile."""
        # noinspection PyTypeChecker
        return collections.Counter(map(CardType, self))


class Deck(CardPile):
    def __init__(self, cards: Sequence[Card], set_aside: Optional[Card]):
        super().__init__(cards)
        self.set_aside: Optional[Card] = set_aside

    # noinspection PyDefaultArgument
    @classmethod
    def from_counts(
        cls: Type[_T], counts: Counter[CardType] = STANDARD_DECK_COUNTS
    ) -> _T:
        return super().from_counts(counts)

    @classmethod
    def from_cards(cls, cards):
        return cls(cards, set_aside=cards.pop() if cards else None)

    def __len__(self) -> int:
        return super().__len__() + int(self.set_aside is not None)

    def __iter__(self) -> Iterator[Card]:
        return (
            mitt.prepend(self.set_aside, super().__iter__())
            if self.set_aside is not None
            else super().__iter__()
        )

    def __contains__(self, x: object) -> bool:
        return super().__contains__(x) or (
            self.set_aside is not None and x == self.set_aside
        )

    def __eq__(self, o: object) -> bool:
        if (result := super().__eq__(o)) is NotImplemented:
            return NotImplemented
        return result and self.set_aside == o.set_aside

    def __repr__(self):
        return (
            f"{self.__class__.__name__}({self.stack}, set_aside={repr(self.set_aside)})"
        )

    def take(self) -> Card:
        return super().take()

    def take_set_aside(self):
        card = self.set_aside
        self.set_aside = None
        return card

    def place(self, card: Card) -> None:
        """Place card on the bottom of the stack"""
        self.stack.insert(0, card)


class DiscardPile(CardPile):
    def take(self) -> Card:
        raise TypeError("Can't take cards from discard pile")

    def place(self, card: Card) -> None:
        super(DiscardPile, self).place(card)


del _T
