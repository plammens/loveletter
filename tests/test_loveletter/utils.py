import collections
import inspect
import random
from typing import Collection, Counter, Type, TypeVar

import loveletter.cards
from loveletter.cardpile import STANDARD_DECK_COUNTS
from loveletter.cards import Card


_T = TypeVar("_T")


def collect_subclasses(base_class: Type[_T], module) -> Collection[Type[_T]]:
    def is_strict_subclass(obj):
        return (
            inspect.isclass(obj)
            and issubclass(obj, base_class)
            and obj is not base_class
        )

    return list(filter(is_strict_subclass, vars(module).values()))


def collect_card_classes() -> Collection[Type[Card]]:
    return collect_subclasses(Card, loveletter.cards)


def random_card_counts() -> Counter[Type[Card]]:
    counts = collections.Counter(
        {
            cls: random.randint(0, max_count)
            for cls, max_count in STANDARD_DECK_COUNTS.items()
        }
    )
    # Remove classes with 0 count:
    for cls, count in tuple(counts.items()):
        if count == 0:
            del counts[cls]
    return counts
