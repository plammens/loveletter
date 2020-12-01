import more_itertools as mitt
import pytest
import pytest_cases
import valid8

import test_loveletter.test_player_cases as cases
from loveletter.player import Player


@pytest.mark.parametrize("id", [0, 1, 2, 3])
def test_newPlayer_validRound_initsCorrectly(game_round, id: int):
    player = Player(game_round, id)
    assert player.round is game_round
    assert player.alive
    assert player.hand.card is None
    assert len(player.cards_played) == 0
    assert player.id == id


def test_handCard_isFirstCard(dummy_player: Player):
    assert dummy_player.hand.card is mitt.first(dummy_player.hand, None)


@pytest_cases.parametrize_with_cases(
    "dummy_player", cases, prefix="player_hand_", indirect=True
)
def test_playerHand_len_isAtMostTwo(dummy_player: Player):
    assert len(dummy_player.hand) <= 2


@pytest_cases.parametrize_with_cases(
    "dummy_player", cases.player_hand_single_card, indirect=True
)
def test_give_playerWithOneCard_oneCard_works(dummy_player: Player):
    card = dummy_player.hand.card
    before = dummy_player.hand.card
    dummy_player.give(card)
    assert list(dummy_player.hand) == [before, card]


@pytest_cases.parametrize_with_cases(
    "dummy_player", cases.player_hand_two_cards, indirect=True
)
def test_give_playerWithTwoCards_oneCard_raises(dummy_player: Player):
    card = dummy_player.hand.card
    with pytest.raises(valid8.ValidationError):
        dummy_player.give(card)
