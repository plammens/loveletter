from typing import Sequence
from unittest.mock import MagicMock

import pytest_cases

import test_loveletter.test_cards_cases as card_cases
from loveletter.cards import Card
from loveletter.player import Player
from loveletter.round import Round, Turn


class PlayerHandCases:
    @pytest_cases.case()
    def case_empty_hand(self):
        return []

    @pytest_cases.case()
    @pytest_cases.parametrize_with_cases("card", cases=card_cases.CardCases)
    def case_single_card(self, card):
        return [card.valuegetter()]

    @pytest_cases.case()
    @pytest_cases.parametrize_with_cases("card1", cases=card_cases.CardCases)
    @pytest_cases.parametrize_with_cases("card2", cases=card_cases.CardCases)
    def case_two_cards(self, card1, card2):
        return [card1.valuegetter(), card2.valuegetter()]


class DummyPlayerCases:
    @staticmethod
    def __make_player(hand: Sequence[Card]) -> Player:
        round_ = Round(2)
        round_.start()
        player = round_.players[0]
        round_mock = MagicMock(wraps=round_)
        player.round = round_mock
        round_mock.state = Turn(player)
        round_mock.current_player = round_mock.state.current_player = player
        round_mock.players = round_.players
        player.hand._cards.clear()
        for card in hand:
            player.give(card)
        return player

    @pytest_cases.case()
    @pytest_cases.parametrize_with_cases(
        "hand", cases=PlayerHandCases().case_empty_hand
    )
    def case_empty_hand(self, hand):
        return DummyPlayerCases.__make_player(hand.valuegetter())

    @pytest_cases.case()
    @pytest_cases.parametrize_with_cases(
        "hand", cases=PlayerHandCases().case_single_card
    )
    def case_single_card(self, hand):
        return DummyPlayerCases.__make_player(hand.valuegetter())

    @pytest_cases.case()
    @pytest_cases.parametrize_with_cases("hand", cases=PlayerHandCases().case_two_cards)
    def case_two_cards(self, hand):
        return DummyPlayerCases.__make_player(hand.valuegetter())


class PlayerCases:
    @pytest_cases.case()
    def case_first_player(self, started_round: Round):
        return started_round.players[0]

    @pytest_cases.case()
    def case_last_player(self, started_round: Round):
        return started_round.players[-1]
