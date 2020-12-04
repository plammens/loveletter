from unittest.mock import MagicMock

import pytest_cases

import loveletter.cards as cards
import loveletter.move as move
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
        def play(owner):
            yield MagicMock()
            yield move.DONE

        mock = MagicMock(spec=Card)
        mock.play.side_effect = play
        return mock
