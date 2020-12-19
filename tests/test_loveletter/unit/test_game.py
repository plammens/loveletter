from typing import List

import pytest
import pytest_cases
import valid8

import loveletter.game
from loveletter.game import Game, GameState
from loveletter.gameevent import GameEvent, GameInputRequest
from loveletter.gamenode import GameNodeState
from loveletter.round import Round, RoundState
from test_loveletter.unit.test_game_cases import (
    INVALID_PLAYER_LIST_CASES,
    PLAYER_LIST_CASES,
)
from test_loveletter.utils import autofill_step


@pytest_cases.parametrize(players=PLAYER_LIST_CASES)
def test_newGame_validPlayerList_works(players: List[str]):
    game = Game(players)
    assert len(game.players) == len(players)
    assert len(set(map(id, game.players))) == len(players)
    assert all(game.players[i].id == i for i in range(len(players)))
    assert not game.started
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
    game_round = state.round
    assert isinstance(game_round, Round)
    assert not game_round.started
    assert game_round.num_players == new_game.num_players


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
