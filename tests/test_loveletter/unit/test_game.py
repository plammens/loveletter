from typing import List

import pytest
import pytest_cases
import valid8

import loveletter.game
from loveletter.game import Game, GameEnd, GameState
from loveletter.gameevent import GameEvent, GameInputRequest
from loveletter.gamenode import GameNodeState
from loveletter.round import Round, RoundState
from test_loveletter.unit.test_game_cases import (
    INVALID_PLAYER_LIST_CASES,
    PLAYER_LIST_CASES,
)
from test_loveletter.utils import autofill_step, autoplay_round, force_end_round


@pytest_cases.parametrize(players=PLAYER_LIST_CASES)
def test_newGame_validPlayerList_works(players: List[str]):
    game = Game(players)
    assert len(game.players) == len(players)
    assert len(set(map(id, game.players))) == len(players)
    assert all(game.players[i].id == i for i in range(len(players)))
    assert not game.started
    assert game.current_round is None
    assert game.state.type == GameState.Type.INIT
    assert set(game.points).issubset(game.players)
    assert all(game.points[p] == 0 for p in game.players)


@pytest_cases.parametrize(players=INVALID_PLAYER_LIST_CASES)
def test_newRound_invalidNumPlayers_raises(players):
    with pytest.raises(valid8.ValidationError):
        Game(players)


def test_start_newGame_setsCorrectGameState(new_game: Game):
    new_game.start()
    assert new_game.started
    assert not new_game.ended
    assert new_game.state.type == GameState.Type.ROUND

    # noinspection PyTypeChecker
    state: loveletter.game.PlayingRound = new_game.state
    assert state.round_no == 1
    assert state.first_player is None

    assert new_game.current_round is state.round
    game_round = new_game.current_round
    assert isinstance(game_round, Round)
    assert not game_round.started
    assert game_round.num_players == new_game.num_players


def test_advance_roundHasEnded_startsNewRound(started_game: Game):
    game_round = started_game.current_round
    assert not game_round.ended
    force_end_round(game_round)
    new_state: loveletter.game.PlayingRound = started_game.advance()
    new_round = new_state.round
    assert new_round is not game_round
    assert started_game.current_round is new_round
    assert not new_round.started


def test_advance_roundNotEnded_raises(started_game: Game):
    game_round = started_game.current_round
    if not game_round.started:
        game_round.start()
    with pytest.raises(valid8.ValidationError):
        started_game.advance()


def test_advance_roundFinished_pointsUpdateCorrectly(started_game: Game):
    game_round = started_game.current_round
    old_points = started_game.points.copy()

    autoplay_round(game_round)
    new_state = started_game.advance()
    assert not new_state.round.started
    winners = {started_game.players[p.id] for p in game_round.state.winners}
    new_points = started_game.points
    diffs = new_points - old_points
    # no negative points:
    assert not -new_points
    # at most one point per player plus the extra spy point:
    assert all(diff <= 2 for diff in diffs.values())
    # winners got at least one point each:
    assert all(diffs[p] >= 1 for p in winners)
    # at most 1 non-winner positive diff
    assert len(set(diffs.keys()) - winners) <= 1
    # at most one diff larger than 1:
    assert sum(int(diff > 1) for diff in diffs.values()) <= 1


@pytest_cases.parametrize(winner=[0, 1, 2])
def test_advance_pointThresholdReached_gameEnds(started_game: Game, winner):
    winner = started_game.players[winner % started_game.num_players]
    started_game.points[winner] = started_game.points_threshold
    force_end_round(started_game.current_round)
    end = started_game.advance()
    assert end.type == GameState.Type.END
    assert end.winner is winner


def test_eventGenerator_yieldsCorrectTypes(new_game: Game):
    def is_game_start(e: GameEvent):
        return isinstance(e, GameState) and e.type == GameState.Type.ROUND

    def is_round_end(e: GameEvent):
        return isinstance(e, GameNodeState) and e.type == RoundState.Type.ROUND_END

    game_generator = new_game.play()
    event = next(game_generator)
    # all input requests until the round starts
    while not is_game_start(event):
        assert isinstance(event, GameInputRequest)
        event = game_generator.send(autofill_step(event))

    # until the round ends, repeat: round -> player move choice -> move steps -> results
    while True:
        # starts with round event
        assert isinstance(event, loveletter.game.PlayingRound)

        # now all of the round events
        event = next(game_generator)
        while not is_round_end(event):
            event = game_generator.send(autofill_step(event))

        # advance (perhaps finish the game)
        try:
            event = next(game_generator)
        except StopIteration as e:
            results = e.value
            break

    assert tuple(r.type for r in results) == (GameNodeState.Type.END,)


def test_advance_moreThanOnePlayerOverPointsThreshold_winnersHaveMaxPoints(
    started_game: Game,
):
    force_end_round(started_game.current_round)
    threshold = started_game.points_threshold

    winners = frozenset(started_game.players[:2])
    for player in winners:
        started_game.points[player] = threshold + 1

    for player in started_game.players[2:]:
        started_game.points[player] = threshold

    end: GameEnd = started_game.advance()  # noqa
    assert end.winners == winners
