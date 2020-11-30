import abc
import collections
import itertools as itt
import random
from typing import Dict, Iterator, List, Sequence, Type, TypeVar

import more_itertools as mitt

from loveletter.cards import (
    Baron,
    Card,
    Chancellor,
    Countess,
    Guard,
    Handmaid,
    King,
    Priest,
    Prince,
    Princess,
    Spy,
)

STANDARD_DECK_COUNTS = {
    Spy: 2,
    Guard: 5,
    Priest: 2,
    Baron: 2,
    Handmaid: 2,
    Prince: 2,
    Chancellor: 2,
    King: 1,
    Countess: 1,
    Princess: 1,
}


class CardPile(collections.abc.Collection, metaclass=abc.ABCMeta):
    def __init__(self, cards: Sequence[Card]):
        self._cards: List[Card] = list(cards)

    # noinspection PyTypeChecker
    _T = TypeVar("_T", bound="CardPile")

    @classmethod
    def from_counts(cls: Type[_T], counts: Dict[Type[Card], int] = None) -> _T:
        if counts is None:
            counts = STANDARD_DECK_COUNTS
        cards = list(
            itt.chain.from_iterable(
                mitt.repeatfunc(card_class, count)
                for card_class, count in counts.items()
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

    @abc.abstractmethod
    def place(self, card: Card) -> None:
        self._cards.append(card)

    @abc.abstractmethod
    def take(self) -> Card:
        return self._cards.pop()


class Deck(CardPile):
    def take(self) -> Card:
        return super(Deck, self).take()

    def place(self, card: Card) -> None:
        raise TypeError("Can't place cards in deck")


class DiscardPile(CardPile):
    def take(self) -> Card:
        raise TypeError("Can't take cards from discard pile")

    def place(self, card: Card) -> None:
        super(DiscardPile, self).place(card)
