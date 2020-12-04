from unittest.mock import MagicMock

import more_itertools as mitt
import pytest_cases

from loveletter.cards import Card
from loveletter.round import Round
from test_loveletter.utils import collect_card_classes


@pytest_cases.case()
@pytest_cases.parametrize("cls", collect_card_classes())
def card_any(cls):
    return cls()


@pytest_cases.case(id="any")
def player_any(game_round: Round):
    return game_round.players[-1]


@pytest_cases.case()
def card_mock() -> MagicMock:
    mock = MagicMock(spec=Card)
    mock.play.return_value = mitt.repeatfunc(MagicMock)
    return mock
