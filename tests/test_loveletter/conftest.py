import pytest

from loveletter.cards import Card
from loveletter.round import Round
from test_loveletter.utils import collect_card_classes


@pytest.fixture(params=(nums := (2, 3, 4)), ids=[f"Round({i})" for i in nums])
def game_round(request) -> Round:
    return Round(num_players=request.param)


@pytest.fixture(params=collect_card_classes())
def card(request) -> Card:
    return request.param()
