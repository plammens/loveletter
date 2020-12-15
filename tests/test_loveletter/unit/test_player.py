import more_itertools as mitt
import pytest
import pytest_cases
import valid8

import test_loveletter.unit.test_cards_cases as card_cases
import test_loveletter.unit.test_player_cases as player_cases
from loveletter.cards import Card
from loveletter.move import CancelMove
from loveletter.roundplayer import RoundPlayer
from test_loveletter.utils import (
    assert_state_is_preserved,
    autofill_move,
    play_card,
)


@pytest.mark.parametrize("id", [0, 1, 2, 3])
def test_newPlayer_validRound_initsCorrectly(game_round, id: int):
    player = RoundPlayer(game_round, id)
    assert player.round is game_round
    assert player.alive
    assert player.hand.card is None
    assert len(player.cards_played) == 0
    assert player.id == id


@pytest_cases.parametrize_with_cases("dummy_player", player_cases.DummyPlayerCases)
def test_handCard_isFirstCard(dummy_player: RoundPlayer):
    assert dummy_player.hand.card is mitt.first(dummy_player.hand, None)


@pytest_cases.parametrize_with_cases("dummy_player", player_cases.DummyPlayerCases)
def test_playerHand_len_isAtMostTwo(dummy_player: RoundPlayer):
    assert len(dummy_player.hand) <= 2


@pytest_cases.parametrize_with_cases(
    "dummy_player", player_cases.DummyPlayerCases.case_single_card
)
def test_give_playerWithOneCard_oneCard_works(dummy_player: RoundPlayer):
    card = dummy_player.hand.card
    before = dummy_player.hand.card
    dummy_player.give(card)
    assert list(dummy_player.hand) == [before, card]


@pytest_cases.parametrize_with_cases(
    "dummy_player",
    player_cases.DummyPlayerCases.case_two_cards,
)
def test_give_playerWithTwoCards_oneCard_raises(dummy_player: RoundPlayer):
    card = dummy_player.hand.card
    with pytest.raises(valid8.ValidationError):
        dummy_player.give(card)


@pytest_cases.parametrize_with_cases("right", cases=card_cases.CardMockCases)
@pytest_cases.parametrize_with_cases("left", cases=card_cases.CardMockCases)
@pytest_cases.parametrize_with_cases(
    "dummy_player", player_cases.DummyPlayerCases.case_empty_hand
)
def test_playCard_left_playsLeftCard(dummy_player: RoundPlayer, left, right):
    dummy_player.give(left)
    dummy_player.give(right)
    autofill_move(dummy_player.play_card(left))
    left.play.assert_called_once_with(dummy_player)
    right.play.assert_not_called()
    assert dummy_player.hand.card is right
    assert left not in dummy_player.hand
    dummy_player.round.discard_pile.place.assert_called_once_with(left)
    assert dummy_player.cards_played[-1] == left


@pytest_cases.parametrize_with_cases("right", cases=card_cases.CardMockCases)
@pytest_cases.parametrize_with_cases("left", cases=card_cases.CardMockCases)
@pytest_cases.parametrize_with_cases(
    "dummy_player", player_cases.DummyPlayerCases.case_empty_hand
)
def test_playCard_right_playsRightCard(dummy_player: RoundPlayer, left, right):
    dummy_player.give(left)
    dummy_player.give(right)
    autofill_move(dummy_player.play_card(right))
    right.play.assert_called_once_with(dummy_player)
    left.play.assert_not_called()
    assert dummy_player.hand.card is left
    assert right not in dummy_player.hand
    dummy_player.round.discard_pile.place.assert_called_once_with(right)
    assert dummy_player.cards_played[-1] == right


@pytest_cases.parametrize_with_cases("player", cases=player_cases.PlayerCases)
def test_eliminate_discardsCards(player: RoundPlayer):
    game_round = player.round
    card = player.hand.card
    player.eliminate()
    assert game_round.discard_pile.top == card
    assert player.cards_played[-1] == card
    assert len(player.hand) == 0


@pytest_cases.parametrize_with_cases("player", cases=player_cases.DummyPlayerCases)
def test_eliminate_deadPlayer_raises(player: RoundPlayer):
    player.eliminate()
    with pytest.raises(valid8.ValidationError):
        player.eliminate()


@pytest_cases.parametrize_with_cases("card", cases=card_cases.CardCases.MultiStepCases)
def test_play_multiStepNoChoice_raises(current_player: RoundPlayer, card: Card):
    move = play_card(current_player, card)
    step = next(move)
    # we don't complete the step and send it right back
    with pytest.raises(valid8.ValidationError):
        move.send(step)


@pytest_cases.parametrize_with_cases(
    "card",
    cases=card_cases.CardCases.MultiStepCases,
    glob="*_cancel",
)
def test_play_cancelMove_stateResetSuccessfully(
    current_player: RoundPlayer, card: Card
):
    move = play_card(current_player, card)
    with assert_state_is_preserved(current_player.round):
        autofill_move(move, num_steps=len(card.steps) - 1)
        with pytest.raises(StopIteration):
            move.throw(CancelMove)
