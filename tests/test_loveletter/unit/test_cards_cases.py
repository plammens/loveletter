import itertools
from unittest.mock import MagicMock

import pytest
import pytest_cases

import loveletter.move as move
from loveletter.cards import Card, CardType
from test_loveletter.utils import card_from_card_type


DISCARD_TYPES = frozenset(t for t in CardType if t.card_class.steps == ())
MULTISTEP_TYPES = frozenset(CardType) - DISCARD_TYPES
NO_CANCEL_TYPES = frozenset(t for t in CardType if not t.card_class.cancellable)
TARGET_TYPES = frozenset(
    t
    for t in CardType
    if (lambda s: len(s) >= 1 and s[0] == move.OpponentChoice)(t.card_class.steps)
)


class CardCases:
    @pytest_cases.case()
    @pytest.mark.parametrize("card_type", DISCARD_TYPES)
    def case_discard_card(self, card_type: CardType):
        return card_from_card_type(card_type)

    class MultiStepCases:
        class TargetCases:
            @pytest_cases.case()
            @pytest.mark.parametrize("card_type", TARGET_TYPES - NO_CANCEL_TYPES)
            def case_target_card_cancel(self, card_type: CardType):
                return card_from_card_type(card_type)

            @pytest_cases.case()
            @pytest.mark.parametrize("card_type", TARGET_TYPES & NO_CANCEL_TYPES)
            def case_target_card_nocancel(self, card_type):
                return card_from_card_type(card_type)

        @pytest_cases.case()
        @pytest.mark.parametrize(
            "card_type", MULTISTEP_TYPES - TARGET_TYPES - NO_CANCEL_TYPES
        )
        def case_other_multistep_cancel(self, card_type: CardType):
            return card_from_card_type(card_type)

        @pytest_cases.case()
        @pytest.mark.parametrize(
            "card_type", (MULTISTEP_TYPES - TARGET_TYPES) & NO_CANCEL_TYPES
        )
        def case_other_multistep_card_nocancel(self, card_type: CardType):
            return card_from_card_type(card_type)


class CardMockCases:
    @pytest_cases.case()
    def case_generic(self) -> MagicMock:
        def play(owner):
            yield MagicMock()
            return (move.MoveResult(owner, mock),)

        mock = MagicMock(spec=Card)
        type(mock).value = 0  # Will look like a Spy, but does nothing
        mock.play.side_effect = play
        return mock


class CardPairCases:
    @pytest_cases.case()
    @pytest.mark.parametrize("type1,type2", itertools.combinations(CardType, r=2))
    def case_ordered_pair(self, type1, type2):
        return type1.card_class(), type2.card_class()
