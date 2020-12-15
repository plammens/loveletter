from typing import Sequence

import pytest_cases
from pytest_cases import CaseGroupMeta

import test_loveletter.unit.test_cards_cases as card_cases
from loveletter.cards import Card
from loveletter.round import Round
from loveletter.roundplayer import RoundPlayer
from test_loveletter.utils import make_round_mock


class PlayerHandCases(metaclass=CaseGroupMeta):
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


class DummyPlayerCases(metaclass=CaseGroupMeta):
    @staticmethod
    def __make_player(hand: Sequence[Card]) -> RoundPlayer:
        round_mock = make_round_mock()
        player = round_mock.current_player
        player.hand._cards.clear()
        for card in hand:
            player.give(card)
        return player

    @pytest_cases.case()
    @pytest_cases.parametrize_with_cases("hand", cases=PlayerHandCases.case_empty_hand)
    def case_empty_hand(self, hand):
        return DummyPlayerCases.__make_player(hand.valuegetter())

    @pytest_cases.case()
    @pytest_cases.parametrize_with_cases("hand", cases=PlayerHandCases.case_single_card)
    def case_single_card(self, hand):
        return DummyPlayerCases.__make_player(hand.valuegetter())

    @pytest_cases.case()
    @pytest_cases.parametrize_with_cases("hand", cases=PlayerHandCases.case_two_cards)
    def case_two_cards(self, hand):
        return DummyPlayerCases.__make_player(hand.valuegetter())


class PlayerCases(metaclass=CaseGroupMeta):
    @pytest_cases.case()
    def case_first_player(self, started_round: Round):
        return started_round.players[0]

    @pytest_cases.case()
    def case_last_player(self, started_round: Round):
        return started_round.players[-1]

    @pytest_cases.case(id="current_player_")
    def case_current_player(self, current_player: RoundPlayer):
        return current_player


class MaybePlayerCases(metaclass=CaseGroupMeta):
    PlayerCases = PlayerCases

    @pytest_cases.case()
    def case_no_player(self):
        return None
