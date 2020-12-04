import pytest_cases

import test_loveletter.cases as cases
from loveletter.cards import Card


@pytest_cases.case()
def player_hand_no_cards():
    return []


@pytest_cases.case()
@pytest_cases.parametrize_with_cases("card", cases=cases.card_any)
def player_hand_single_card(card: Card):
    return [card]


@pytest_cases.case()
@pytest_cases.parametrize_with_cases("card1", cases=cases.card_any)
@pytest_cases.parametrize_with_cases("card2", cases=cases.card_any)
def player_hand_two_cards(card1: Card, card2: Card):
    return [card1, card2]
