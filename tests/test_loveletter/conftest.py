import random

import pytest
import pytest_cases

from loveletter.round import Round

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
