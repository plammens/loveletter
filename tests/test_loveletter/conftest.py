import copy
import random

import more_itertools as mitt
import pytest
import pytest_cases

import test_loveletter.cases as cases
import test_loveletter.test_player_cases as player_cases
from loveletter.cardpile import Deck, DiscardPile, STANDARD_DECK_COUNTS
from loveletter.cards import Card
from loveletter.round import Round
from test_loveletter.utils import random_card_counts

random.seed(2020)


@pytest_cases.fixture()
@pytest.mark.parametrize("num_players", (2, 3, 4), ids=lambda n: f"Round({n})")
def new_round(num_players) -> Round:
    return Round(num_players)


@pytest_cases.fixture()
def started_round(new_round: Round):
    new_round.start()
    return new_round


game_round = pytest_cases.fixture_union("game_round", [new_round, started_round])


@pytest_cases.fixture()
@pytest_cases.parametrize_with_cases("card", cases=cases, prefix="card_")
def card(card) -> Card:
    return card


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


@pytest_cases.fixture()
@pytest_cases.parametrize_with_cases(
    "player", cases=player_cases, prefix="dummy_player_"
)
def dummy_player(player):
    # Make a copy of the player to avoid leaking state across test invocations (nodes)
    return copy.deepcopy(player)
