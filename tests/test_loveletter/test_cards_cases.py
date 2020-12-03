import pytest_cases

import loveletter.cards as cards


@pytest_cases.case()
@pytest_cases.parametrize(
    "card_cls", [cards.Spy, cards.Handmaid, cards.Countess, cards.Princess]
)
def card_discard(card_cls):
    return card_cls()


@pytest_cases.case()
@pytest_cases.parametrize(
    "card_cls", [cards.Guard, cards.Priest, cards.Baron, cards.Prince, cards.King]
)
def card_target(card_cls):
    return card_cls()
