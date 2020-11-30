import pytest
import valid8

import loveletter.cards as cards
from test_loveletter.utils import collect_card_classes


def test_cards_have_unique_nonnegative_value():
    classes = collect_card_classes()
    values = {cls.value for cls in classes}
    assert len(values) == len(classes)
    assert all(type(v) is int for v in values)
    assert all(v >= 0 for v in values)


@pytest.mark.parametrize(
    "card", [cards.Spy, cards.Handmaid, cards.Countess, cards.Princess], indirect=True
)
def test_play_discardCard_targetNotNone_raises(card: cards.Card, player1, player2):
    with pytest.raises(valid8.ValidationError):
        card.play(player1, player2)


@pytest.mark.parametrize(
    "card",
    [cards.Guard, cards.Priest, cards.Baron, cards.Prince, cards.King],
    indirect=True,
)
def test_play_targetCard_targetNone_raises(card: cards.Card, player1):
    with pytest.raises(valid8.ValidationError):
        card.play(player1, None)
