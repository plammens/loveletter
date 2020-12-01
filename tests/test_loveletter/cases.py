import pytest_cases

from loveletter.cards import Card
from loveletter.player import Player
from test_loveletter.utils import collect_card_classes


@pytest_cases.parametrize("cls", collect_card_classes())
def card_any(cls):
    return cls()


def dummy_player_without_card():
    # noinspection PyTypeChecker
    return Player(None, 0)


@pytest_cases.parametrize_with_cases("card", cases=".", prefix="card_")
def dummy_player_with_card(card: Card):
    # noinspection PyTypeChecker
    player = Player(None, 0)
    player.give(card)
    return player


@pytest_cases.parametrize_with_cases("card1", cases=".", prefix="card_")
@pytest_cases.parametrize_with_cases("card2", cases=".", prefix="card_")
def dummy_player_with_two_cards(card1: Card, card2: Card):
    # noinspection PyTypeChecker
    player = Player(None, 0)
    player.give(card1)
    player.give(card2)
    return player
