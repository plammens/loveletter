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


@pytest_cases.parametrize_with_cases("player", cases, prefix="dummy_player_")
def test_playerHand_len_isAtMostTwo(player: Player):
    assert len(player.hand) < 2


@pytest_cases.parametrize_with_cases("player", cases.dummy_player_with_card)
def test_give_playerWithOneCard_oneCard_works(player: Player, card):
    before = player.hand.card
    player.give(card)
    assert list(player.hand) == [before, card]


@pytest_cases.parametrize_with_cases("player", cases.dummy_player_with_two_cards)
def test_give_playerWithTwoCards_oneCard_raises(player: Player, card):
    with pytest.raises(valid8.ValidationError):
        player.give(card)
