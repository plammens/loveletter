import pytest

from loveletter.game import Game
from loveletter.player import Player


@pytest.mark.parametrize("id", [0, 1, 2, 3])
def test_newPlayer_validGame_initsCorrectly(game: Game, id: int):
    player = Player(game, id)
    assert player.game is game
    assert player.alive
    assert player.hand.card is None
    assert len(player.cards_played) == 0
    assert player.id == id
