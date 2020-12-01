import random

import more_itertools as mitt
import pytest
import pytest_cases

from loveletter.cardpile import Deck, DiscardPile, STANDARD_DECK_COUNTS
from loveletter.cards import Card
from loveletter.round import Round
from test_loveletter.utils import collect_card_classes, random_card_counts

random.seed(2020)


@pytest.fixture(params=(nums := (2, 3, 4)), ids=[f"Round({i})" for i in nums])
def game_round(request) -> Round:
    return Round(num_players=request.param)


@pytest.fixture(params=collect_card_classes())
def card(request) -> Card:
    return request.param()


@pytest_cases.fixture()
@pytest.mark.parametrize(
    "counts", [{}, *mitt.repeatfunc(random_card_counts, 5), STANDARD_DECK_COUNTS]
)
def deck(counts) -> Deck:
    return Deck.from_counts(counts)


@pytest_cases.fixture()
@pytest.mark.parametrize(
    "counts",
    [{}, *mitt.repeatfunc(random_card_counts, 5), STANDARD_DECK_COUNTS],
)
def discard_pile(counts) -> DiscardPile:
    return DiscardPile.from_counts(counts)


card_pile = pytest_cases.fixture_union("card_pile", [deck, discard_pile])
