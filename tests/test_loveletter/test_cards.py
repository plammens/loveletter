import pytest
import pytest_cases
import valid8

import loveletter.cards as cards
import loveletter.move
import test_loveletter.test_cards_cases as card_cases
import test_loveletter.test_player_cases as player_cases
from loveletter.player import Player
from loveletter.round import Round, Turn
from test_loveletter.utils import (
    autofill_step,
    force_next_turn,
    make_mock_move,
    play_card,
    play_card_with_cleanup,
)


def test_cards_have_unique_nonnegative_value():
    values = {t.value for t in cards.CardType}
    assert len(values) == len(cards.CardType)
    assert all(type(v) is int for v in values)
    assert all(v >= 0 for v in values)


@pytest_cases.parametrize_with_cases("card", cases=card_cases.CardCases)
@pytest_cases.parametrize_with_cases(
    "player", cases=player_cases.DummyPlayerCases().case_single_card
)
def test_cardSteps_correspondsToReality(player: Player, card: cards.Card):
    move = play_card(player, card, autofill=False)
    step = None
    for expected_step_type in card.steps:
        step = move.send(autofill_step(step))
        assert type(step) == expected_step_type
    assert isinstance(move.send(autofill_step(step)), loveletter.move.MoveResult)


def test_spy_noOnePlayed_noOneGetsPoint(started_round: Round):
    for player in started_round.players[1:]:
        player.eliminate()
    force_next_turn(started_round)
    assert cards.Spy.collect_extra_points(started_round) == {}


def test_spy_onePlayed_getsPoint(started_round: Round):
    first = started_round.current_player
    play_card(first, cards.Spy())
    for player in started_round.players:
        if player is not first:
            player.eliminate()
    started_round.advance_turn()
    assert cards.Spy.collect_extra_points(started_round) == {first: 1}


def test_spy_onePlayed_getsPointEvenIfDead(started_round: Round):
    first = started_round.current_player
    second = started_round.next_player(first)
    play_card(first, cards.Spy())
    for player in started_round.players:
        if player is not second:
            player.eliminate()
    started_round.advance_turn()
    assert cards.Spy.collect_extra_points(started_round) == {first: 1}


def test_spy_twoPlayed_noOneGetsPoint(started_round: Round):
    first = started_round.current_player
    second = started_round.next_player(first)
    play_card(first, cards.Spy())
    started_round.advance_turn()
    play_card(second, cards.Spy())
    for player in started_round.players[1:]:
        player.eliminate()
    started_round.advance_turn()
    assert cards.Spy.collect_extra_points(started_round) == {}


def test_guard_correctGuess_eliminatesOpponent(started_round: Round):
    player = started_round.current_player
    for other in set(started_round.players) - {player}:
        assert other.alive
        move = play_card(player, cards.Guard())
        target_step = move.send(None)
        target_step.choice = other
        guess_step = move.send(target_step)
        guess_step.choice = type(other.hand.card)
        move.send(guess_step)
        move.close()
        assert not other.alive
        # artificially start new turn with same player
        started_round.state = Turn(player)


def test_guard_incorrectGuess_doesNotEliminateOpponent(started_round: Round):
    player = started_round.current_player
    for other in set(started_round.players) - {player}:
        assert other.alive
        for wrong_type in set(cards.CardType) - {cards.CardType(type(other.hand.card))}:
            move = play_card(player, cards.Guard())
            target_step = next(move)
            target_step.choice = other
            guess_step = move.send(target_step)
            guess_step.choice = wrong_type
            move.send(guess_step)
            move.close()
            assert other.alive
            # artificially start new turn with same player
            started_round.state = Turn(player)


def test_priest_validOpponent_showsCard(started_round: Round):
    player = started_round.current_player
    opponent = started_round.next_player(player)
    move = play_card(player, cards.Priest())
    target_step = next(move)
    target_step.choice = opponent
    result = move.send(target_step)
    assert isinstance(result, loveletter.move.ShowOpponentCard)
    move.close()
    assert result.opponent is opponent


def test_handmaid_playerBecomesImmune(current_player: Player):
    play_card(current_player, cards.Handmaid())
    assert current_player.immune


@pytest_cases.parametrize_with_cases("card", card_cases.case_target_card)
def test_targetCard_againstImmunePlayer_raises(started_round: Round, card):
    immune_player = started_round.current_player
    play_card(immune_player, cards.Handmaid())
    # should be immune now
    started_round.advance_turn()
    opponent = started_round.current_player
    with play_card_with_cleanup(opponent, card) as move:
        target_step = next(move)
        with pytest.raises(valid8.ValidationError):
            target_step.choice = immune_player
            move.send(target_step)


def test_handmaid_immunityLastsOneFullRotation(started_round: Round):
    immune_player = started_round.current_player
    play_card(immune_player, cards.Handmaid())
    started_round.advance_turn()
    while (current := started_round.current_player) is not immune_player:
        assert immune_player.immune
        make_mock_move(current)
        started_round.advance_turn()
    assert not immune_player.immune


def test_handmaid_immunityLastsOneFullRotation_withDeaths(started_round: Round):
    immune_player = started_round.current_player
    play_card(immune_player, cards.Handmaid())
    started_round.advance_turn()
    killer = started_round.current_player
    for player in set(started_round.players) - {immune_player, killer}:
        assert immune_player.immune
        player.eliminate()
    assert immune_player.immune
    force_next_turn(started_round)
    assert not immune_player.immune


@pytest_cases.parametrize_with_cases("card", cases=card_cases.case_target_card)
def test_targetCard_chooseSelf_raises(current_player, card):
    with play_card_with_cleanup(current_player, card) as move:
        target_step = next(move)
        with pytest.raises(valid8.ValidationError):
            target_step.choice = current_player
            move.send(target_step)
