from unittest.mock import MagicMock

import more_itertools as mitt
import pytest_cases

import loveletter.cards as cards
from loveletter.cards import Card


class CardCases:
    @pytest_cases.case()
    @pytest_cases.parametrize(
        "card_cls", [cards.Spy, cards.Handmaid, cards.Countess, cards.Princess]
    )
    def case_discard_card(self, card_cls):
        return card_cls()

    @pytest_cases.case()
    @pytest_cases.parametrize(
        "card_cls", [cards.Guard, cards.Priest, cards.Baron, cards.Prince, cards.King]
    )
    def case_target_card(self, card_cls):
        return card_cls()


class CardMockCases:
    @pytest_cases.case()
    def case_generic(self) -> MagicMock:
        mock = MagicMock(spec=Card)
        mock.play.return_value = mitt.repeatfunc(MagicMock)
        return mock
