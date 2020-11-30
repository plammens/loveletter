import pytest
import valid8

from loveletter.round import Round, RoundEnd, RoundState, Turn


@pytest.mark.parametrize("num_players", [2, 3, 4])
def test_newRound_validNumPlayers_works(num_players: int):
    round = Round(num_players=num_players)
    assert len(round.players) == num_players
    assert len(set(map(id, round.players))) == num_players
    assert all(player.round is round for player in round.players)
    assert all(round.players[i].id == i for i in range(num_players))


@pytest.mark.parametrize("num_players", ["foo", -1, 0, 1, 5])
def test_newRound_invalidNumPlayers_raises(num_players):
    with pytest.raises(valid8.ValidationError):
        Round(num_players)


def test_currentPlayer_isValid(round: Round):
    assert round.current_player.alive


def test_nextTurn_currentPlayerIsValid(round: Round):
    before = round.current_player
    round.next_turn()
    after = round.current_player
    assert after.alive
    assert after is not before


def test_nextTurn_ongoingRound_roundStateIsTurn(round: Round):
    state = round.next_turn()
    assert state.type == RoundState.Type.TURN
    assert isinstance(state, Turn)


def test_nextTurn_onlyOnePlayerRemains_roundStateIsEnd(round: Round):
    winner = round.players[-1]
    for player in round.players:
        if player is not winner:
            player.eliminate()
    state = round.next_turn()
    assert state.type == RoundState.Type.ROUND_END
    assert isinstance(state, RoundEnd)
    assert state.winner is winner
