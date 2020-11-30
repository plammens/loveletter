import pytest
import valid8

from loveletter.game import Game, GameEnd, GameState, Turn


@pytest.mark.parametrize("num_players", [2, 3, 4])
def test_newGame_validNumPlayers_works(num_players: int):
    game = Game(num_players=num_players)
    assert len(game.players) == num_players
    assert len(set(map(id, game.players))) == num_players
    assert all(player.game is game for player in game.players)
    assert all(game.players[i].id == i for i in range(num_players))


@pytest.mark.parametrize("num_players", ["foo", -1, 0, 1, 5])
def test_newGame_invalidNumPlayers_raises(num_players):
    with pytest.raises(valid8.ValidationError):
        Game(num_players)


def test_currentPlayer_isValid(game: Game):
    assert game.current_player.alive


def test_nextTurn_currentPlayerIsValid(game: Game):
    before = game.current_player
    game.next_turn()
    after = game.current_player
    assert after.alive
    assert after is not before


def test_nextTurn_ongoingGame_gameStateIsTurn(game: Game):
    state = game.next_turn()
    assert state.type == GameState.Type.TURN
    assert isinstance(state, Turn)


def test_nextTurn_onlyOnePlayerRemains_gameStateIsEnd(game: Game):
    winner = game.players[-1]
    for player in game.players:
        if player is not winner:
            player.eliminate()
    state = game.next_turn()
    assert state.type == GameState.Type.GAME_END
    assert isinstance(state, GameEnd)
    assert state.winner is winner
