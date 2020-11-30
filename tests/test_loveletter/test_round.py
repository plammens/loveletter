import pytest
import valid8

from loveletter.round import Round, RoundEnd, RoundState, Turn


@pytest.mark.parametrize("num_players", [2, 3, 4])
def test_newRound_validNumPlayers_works(num_players: int):
    game_round = Round(num_players=num_players)
    assert len(game_round.players) == num_players
    assert len(set(map(id, game_round.players))) == num_players
    assert all(player.round is game_round for player in game_round.players)
    assert all(game_round.players[i].id == i for i in range(num_players))


@pytest.mark.parametrize("num_players", ["foo", -1, 0, 1, 5])
def test_newRound_invalidNumPlayers_raises(num_players):
    with pytest.raises(valid8.ValidationError):
        Round(num_players)


def test_currentPlayer_isValid(game_round):
    assert game_round.current_player.alive


def test_nextTurn_currentPlayerIsValid(game_round):
    before = game_round.current_player
    game_round.next_turn()
    after = game_round.current_player
    assert after.alive
    assert after is not before


def test_nextTurn_ongoingRound_roundStateIsTurn(game_round):
    state = game_round.next_turn()
    assert state.type == RoundState.Type.TURN
    assert isinstance(state, Turn)


def test_nextTurn_onlyOnePlayerRemains_roundStateIsEnd(game_round):
    winner = game_round.players[-1]
    for player in game_round.players:
        if player is not winner:
            player.eliminate()
    state = game_round.next_turn()
    assert state.type == RoundState.Type.ROUND_END
    assert isinstance(state, RoundEnd)
    assert state.winner is winner
