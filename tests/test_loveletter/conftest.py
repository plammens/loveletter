import random

import more_itertools as mitt
import pytest
import pytest_cases

from loveletter.cardpile import Deck, DiscardPile, STANDARD_DECK_COUNTS
from loveletter.cards import Card
from loveletter.round import Round
from test_loveletter.utils import collect_card_classes, random_card_counts

random.seed(2020)


@pytest_cases.fixture()
@pytest.mark.parametrize("num_players", (2, 3, 4), ids=lambda n: f"Round({n})")
def game_round(num_players) -> Round:
    return Round(num_players)


@pytest_cases.fixture()
@pytest.mark.parametrize("card_class", collect_card_classes())
def card(card_class) -> Card:
    return card_class()


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
