from loveletter.game import Game
from loveletter.player import Player


def test_newPlayer_validGame_initsCorrectly(game: Game):
    player = Player(game)
    assert player.game is game
    assert player.alive
    assert player.hand.card is None
    assert len(player.cards_played) == 0
