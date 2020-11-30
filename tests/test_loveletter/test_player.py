import pytest

from loveletter.player import Player
from loveletter.round import Round


@pytest.mark.parametrize("id", [0, 1, 2, 3])
def test_newPlayer_validRound_initsCorrectly(round: Round, id: int):
    player = Player(round, id)
    assert player.round is round
    assert player.alive
    assert player.hand.card is None
    assert len(player.cards_played) == 0
    assert player.id == id
