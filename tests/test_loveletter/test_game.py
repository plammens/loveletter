import pytest
import valid8

from loveletter.game import Game


@pytest.mark.parametrize("num_players", [2, 3, 4])
def test_newGame_validNumPlayers_works(num_players: int):
    game = Game(num_players=num_players)
    assert len(game.players) == num_players
    assert len(set(map(id, game.players))) == num_players
    assert all(player.game is game for player in game.players)


@pytest.mark.parametrize("num_players", ["foo", -1, 0, 1, 5])
def test_newGame_invalidNumPlayers_raises(num_players):
    with pytest.raises(valid8.ValidationError):
        Game(num_players)
