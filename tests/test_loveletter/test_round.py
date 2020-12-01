import pytest
import valid8

from loveletter.cardpile import Deck, STANDARD_DECK_COUNTS
from loveletter.round import Round, RoundEnd, RoundState, Turn
from test_loveletter.test_round_cases import INVALID_NUM_PLAYERS, VALID_NUM_PLAYERS


@pytest.mark.parametrize("num_players", VALID_NUM_PLAYERS)
def test_newRound_validNumPlayers_works(num_players: int):
    game_round = Round(num_players=num_players)
    assert len(game_round.players) == num_players
    assert len(set(map(id, game_round.players))) == num_players
    assert all(player.round is game_round for player in game_round.players)
    assert all(game_round.players[i].id == i for i in range(num_players))
    assert not game_round.started
    assert game_round.state.type == RoundState.Type.INIT


@pytest.mark.parametrize("num_players", INVALID_NUM_PLAYERS)
def test_newRound_invalidNumPlayers_raises(num_players):
    with pytest.raises(valid8.ValidationError):
        Round(num_players)


@pytest.mark.parametrize("num_players", VALID_NUM_PLAYERS)
def test_newRound_validNumPlayers_hasStandardDeck(num_players: int):
    game_round = Round(num_players=num_players)
    assert game_round.deck == Deck.from_counts(STANDARD_DECK_COUNTS)


def test_start_newRound_setsCorrectGameState(game_round: Round):
    assert game_round.current_player is None
    game_round.start()
    assert game_round.current_player in game_round.players
    assert game_round.started
    assert game_round.state.type == RoundState.Type.TURN
    assert game_round.state.current_player == game_round.current_player


def test_currentPlayer_isValid(started_round):
    assert started_round.current_player.alive


def test_nextTurn_currentPlayerIsValid(started_round):
    before = started_round.current_player
    started_round.next_turn()
    after = started_round.current_player
    assert after.alive
    assert after is not before


def test_nextTurn_ongoingRound_roundStateIsTurn(started_round):
    state = started_round.next_turn()
    assert state.type == RoundState.Type.TURN
    assert isinstance(state, Turn)


def test_nextTurn_onlyOnePlayerRemains_roundStateIsEnd(started_round):
    winner = started_round.players[-1]
    for player in started_round.players:
        if player is not winner:
            player.eliminate()
    state = started_round.next_turn()
    assert state.type == RoundState.Type.ROUND_END
    assert isinstance(state, RoundEnd)
    assert state.winner is winner
