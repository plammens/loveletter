import pytest
import valid8

import loveletter.cards as cards
from loveletter.round import Round
from test_loveletter.utils import autofill_moves, send_gracious


def test_cards_have_unique_nonnegative_value():
    values = {t.value for t in cards.CardType}
    assert len(values) == len(cards.CardType)
    assert all(type(v) is int for v in values)
    assert all(v >= 0 for v in values)


def test_spy_noOnePlayed_noOneGetsPoint(started_round: Round):
    for player in started_round.players[1:]:
        player.eliminate()
    started_round.next_turn()
    assert cards.Spy.collect_extra_points(started_round) == {}


def test_spy_onePlayed_getsPoint(started_round: Round):
    first = started_round.current_player
    first.give(cards.Spy())
    autofill_moves(first.play_card("right"))
    for player in started_round.players:
        if player is not first:
            player.eliminate()
    started_round.next_turn()
    assert cards.Spy.collect_extra_points(started_round) == {first: 1}


def test_spy_onePlayed_getsPointEvenIfDead(started_round: Round):
    first = started_round.current_player
    second = started_round.players[(first.id + 1) % started_round.num_players]
    first.give(cards.Spy())
    autofill_moves(first.play_card("right"))
    for player in started_round.players:
        if player is not second:
            player.eliminate()
    started_round.next_turn()
    assert cards.Spy.collect_extra_points(started_round) == {first: 1}


def test_spy_twoPlayed_noOneGetsPoint(started_round: Round):
    first = started_round.current_player
    second = started_round.players[(first.id + 1) % started_round.num_players]
    first.give(cards.Spy())
    autofill_moves(first.play_card("right"))
    started_round.next_turn()
    second.give(cards.Spy())
    autofill_moves(second.play_card("right"))
    for player in started_round.players[1:]:
        player.eliminate()
    started_round.next_turn()
    assert cards.Spy.collect_extra_points(started_round) == {}


def test_guard_chooseOneSelf_raises(started_round: Round):
    player = started_round.current_player
    player.give(cards.Guard())
    move = player.play_card("right")
    target_step = move.send(None)
    with pytest.raises(valid8.ValidationError):
        target_step.choice = player
        move.send(target_step)


def test_guard_correctGuess_eliminatesOpponent(started_round: Round):
    player = started_round.current_player
    for other in set(started_round.players) - {player}:
        assert other.alive
        player.give(cards.Guard())
        move = player.play_card("right")
        target_step = move.send(None)
        target_step.choice = other
        guess_step = move.send(target_step)
        guess_step.choice = type(other.hand.card)
        send_gracious(move, guess_step)
        assert not other.alive


def test_guard_incorrectGuess_doesNotEliminateOpponent(started_round: Round):
    player = started_round.current_player
    for other in set(started_round.players) - {player}:
        assert other.alive
        for wrong_type in set(cards.CardType) - {cards.CardType(type(other.hand.card))}:
            player.give(cards.Guard())
            move = player.play_card("right")
            target_step = move.send(None)
            target_step.choice = other
            guess_step = move.send(target_step)
            guess_step.choice = wrong_type
            send_gracious(move, guess_step)
            assert other.alive
