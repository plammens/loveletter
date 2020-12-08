import itertools
from unittest.mock import MagicMock

import pytest_cases

import loveletter.move as move
from loveletter.cards import Card, CardType

DISCARD_TYPES = {t for t in CardType if t.card_class.steps == ()}
TARGET_TYPES = {
    t
    for t in CardType
    if (lambda s: len(s) >= 1 and s[0] == move.OpponentChoice)(t.card_class.steps)
}


class CardCases:
    @pytest_cases.case()
    @pytest_cases.parametrize(card_type=DISCARD_TYPES)
    def case_discard_card(self, card_type: CardType):
        return card_type.card_class()

    @pytest_cases.case()
    @pytest_cases.parametrize(card_type=set(CardType) - DISCARD_TYPES)
    def case_multistep_card(self, card_type: CardType):
        return card_type.card_class()


@pytest_cases.parametrize(card_type=TARGET_TYPES)
def case_target_card(card_type: CardType):
    return card_type.card_class()


class CardMockCases:
    @pytest_cases.case()
    def case_generic(self) -> MagicMock:
        def play(owner):
            yield MagicMock()
            return (move.MoveResult(owner, mock),)

        mock = MagicMock(spec=Card)
        mock.play.side_effect = play
        return mock


class CardPairCases:
    @pytest_cases.case()
    @pytest_cases.parametrize("type1,type2", itertools.combinations(CardType, r=2))
    def case_ordered_pair(self, type1, type2):
        return type1.card_class(), type2.card_class()
