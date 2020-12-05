import collections
import inspect
import random
from typing import Any, Collection, Counter, Generator, Type, TypeVar

import pytest

from loveletter import cards as cards
from loveletter.cardpile import STANDARD_DECK_COUNTS
from loveletter.cards import Card
from loveletter.move import MoveStep
from loveletter.player import Player
from test_loveletter import test_cards_cases as card_cases


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


def send_final(gen: Generator, value: Any) -> Any:
    try:
        with pytest.raises(StopIteration):
            return gen.send(value)
    except StopIteration as e:
        return e.value


def make_mock_move(player):
    card_mock = card_cases.CardMockCases().case_generic()
    player.give(card_mock)
    autofill_moves(player.play_card("right"))
