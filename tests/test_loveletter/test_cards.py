import pytest
import pytest_cases
import valid8

import loveletter.cards as cards
import test_loveletter.cases as cases
import test_loveletter.test_cards_cases as card_cases
from test_loveletter.utils import collect_card_classes


def test_cards_have_unique_nonnegative_value():
    classes = collect_card_classes()
    values = {cls.value for cls in classes}
    assert len(values) == len(classes)
    assert all(type(v) is int for v in values)
    assert all(v >= 0 for v in values)


@pytest_cases.parametrize_with_cases("player2", cases=cases.player_any)
@pytest_cases.parametrize_with_cases("player1", cases=cases.player_any)
@pytest_cases.parametrize_with_cases("card", cases=card_cases.card_discard)
def test_play_discardCard_targetNotNone_raises(card: cards.Card, player1, player2):
    with pytest.raises(valid8.ValidationError):
        card.play(player1, player2)


@pytest_cases.parametrize_with_cases("player", cases=cases.player_any)
@pytest_cases.parametrize_with_cases("card", cases=card_cases.card_target)
def test_play_targetCard_targetNone_raises(card: cards.Card, player):
    with pytest.raises(valid8.ValidationError):
        card.play(player, None)
