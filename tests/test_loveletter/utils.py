import collections
import inspect
import random
from typing import Any, Collection, Counter, Generator, Type, TypeVar

from loveletter.cardpile import STANDARD_DECK_COUNTS
from loveletter.cards import Card
from loveletter.move import MoveStep


_T = TypeVar("_T")


def collect_subclasses(base_class: Type[_T], module) -> Collection[Type[_T]]:
    def is_strict_subclass(obj):
        return (
            inspect.isclass(obj)
            and issubclass(obj, base_class)
            and obj is not base_class
        )

    return list(filter(is_strict_subclass, vars(module).values()))


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


def autofill_moves(steps: Generator[MoveStep, MoveStep, None]):
    # for now just consume generator
    step = None
    # fmt: off
    try:
        while True: step = steps.send(step)
    except StopIteration: pass
    # fmt: on


def send_gracious(gen: Generator, value: Any) -> Any:
    try:
        return gen.send(value)
    except StopIteration as e:
        return e.value
