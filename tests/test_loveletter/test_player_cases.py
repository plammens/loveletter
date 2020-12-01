import pytest_cases

import test_loveletter.cases as cases
from loveletter.cards import Card
from loveletter.player import Player


def dummy_player_without_card():
    # noinspection PyTypeChecker
    return Player(None, 0)


@pytest_cases.parametrize_with_cases("card", cases=cases.card_any)
def dummy_player_with_card(card: Card):
    # noinspection PyTypeChecker
    player = Player(None, 0)
    player.give(card)
    return player


@pytest_cases.parametrize_with_cases("card1", cases=cases.card_any)
@pytest_cases.parametrize_with_cases("card2", cases=cases.card_any)
def dummy_player_with_two_cards(card1: Card, card2: Card):
    # noinspection PyTypeChecker
    player = Player(None, 0)
    player.give(card1)
    player.give(card2)
    return player
