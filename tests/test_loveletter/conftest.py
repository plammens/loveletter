import pytest

from loveletter.cards import Card
from loveletter.game import Game
from test_loveletter.utils import collect_card_classes


@pytest.fixture(params=(2, 3, 4))
def game(request) -> Game:
    return Game(num_players=request.param)


@pytest.fixture(params=collect_card_classes())
def card(request) -> Card:
    return request.param()
