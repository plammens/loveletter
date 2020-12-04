from unittest.mock import MagicMock

import pytest_cases

from loveletter.cards import Card, CardType

DISCARD_TYPES = {CardType.SPY, CardType.HANDMAID, CardType.COUNTESS, CardType.PRINCESS}


class CardCases:
    @pytest_cases.case()
    @pytest_cases.parametrize(card_type=DISCARD_TYPES)
    def case_discard_card(self, card_type: CardType):
        return card_type.card_class()

    @pytest_cases.case()
    @pytest_cases.parametrize(card_type=set(CardType) - DISCARD_TYPES)
    def case_multistep_card(self, card_type: CardType):
        return card_type.card_class()


class CardMockCases:
    @pytest_cases.case()
    def case_generic(self) -> MagicMock:
        def play(owner):
            yield MagicMock()

        mock = MagicMock(spec=Card)
        mock.play.side_effect = play
        return mock
