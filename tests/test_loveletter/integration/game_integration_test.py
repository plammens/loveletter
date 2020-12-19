import loveletter.cards as cards
from loveletter.cards import CardType
from loveletter.game import Game
from loveletter.round import RoundState
from test_loveletter.utils import (
    play_random_move,
    play_with_choices,
    start_round_from_player_cards,
)


def test_1_repeated_win():
    def round_runner(g):
        game_round = start_round_from_player_cards(
            [cards.Guard(), cards.Baron()],
            [cards.King(), cards.Princess()],
            first_player=0,
        )
        object.__setattr__(g.state, "round", game_round)  # work around frozen dataclass
        player0, player1 = game_round.players

        play_with_choices(player0, CardType.GUARD, player1, cards.Princess)
        play_random_move(player1)

        end = game_round.state
        assert end.type == RoundState.Type.ROUND_END
        assert end.winner is player0

    game = Game(["Alice", "Bob"])
    alice, bob = game.players
    game.start()
    for i in range(1, 8):
        assert game.state.round_no == i
        round_runner(game)
        game.advance()
        assert +game.points == {alice: i}

    assert game.ended
    assert game.state.winner is alice
