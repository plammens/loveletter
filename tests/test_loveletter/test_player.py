import pytest

from loveletter.player import Player


@pytest.mark.parametrize("id", [0, 1, 2, 3])
def test_newPlayer_validRound_initsCorrectly(game_round, id: int):
    player = Player(game_round, id)
    assert player.round is game_round
    assert player.alive
    assert player.hand.card is None
    assert len(player.cards_played) == 0
    assert player.id == id
