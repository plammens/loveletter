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
        CardType.GUARD: 5,
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


class CardPile(collections.abc.Collection, metaclass=abc.ABCMeta):
    def __init__(self, cards: Sequence[Card]):
        self._cards: List[Card] = list(cards)

    # noinspection PyTypeChecker
    _T = TypeVar("_T", bound="CardPile")

    @classmethod
    def from_counts(cls: Type[_T], counts: Counter[CardType] = None) -> _T:
        if counts is None:
            counts = STANDARD_DECK_COUNTS
        cards = list(
            itt.chain.from_iterable(
                mitt.repeatfunc(card_type.card_class, count)
                for card_type, count in counts.items()
            )
        )
        random.shuffle(cards)
        return cls(cards)

    del _T

    def __len__(self) -> int:
        return len(self._cards)

    def __iter__(self) -> Iterator[Card]:
        return iter(self._cards)

    def __contains__(self, x: object) -> bool:
        return x in self._cards

    def __eq__(self, o: object) -> bool:
        """Two piles are equal if they contain the same distribution of cards."""
        if not isinstance(o, self.__class__):
            raise TypeError(f"{self} and {o} not comparable")
        return self.get_counts() == o.get_counts()

    @property
    def top(self) -> Optional[Card]:
        return self._cards[-1] if len(self._cards) else None

    @abc.abstractmethod
    def place(self, card: Card) -> None:
        self._cards.append(card)

    @abc.abstractmethod
    def take(self) -> Card:
        return self._cards.pop()

    def get_counts(self) -> Counter[CardType]:
        """Returns a dictionary of card type to count in the pile."""
        # noinspection PyTypeChecker
        return collections.Counter(map(CardType, self))


class Deck(CardPile):
    # TODO: hold out one card

    def take(self) -> Card:
        return super(Deck, self).take()

    def place(self, card: Card) -> None:
        raise TypeError("Can't place cards in deck")


class DiscardPile(CardPile):
    def take(self) -> Card:
        raise TypeError("Can't take cards from discard pile")

    def place(self, card: Card) -> None:
        super(DiscardPile, self).place(card)
