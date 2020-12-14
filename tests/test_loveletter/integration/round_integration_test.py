import loveletter.cards as cards
import loveletter.move as move
from loveletter.cardpile import Deck
from loveletter.cards import CardType
from loveletter.round import Round, RoundState
from test_loveletter.utils import make_round_from_player_cards, play_with_choices


def test_1_prince_victory():
    """
    player1 has a countess, player0 uses a prince to discard himself and get the
    princess and win.
    """
    deck = Deck(
        [
            cards.Prince(),
            cards.Countess(),
            cards.Handmaid(),
            cards.Priest(),
            cards.Guard(),
        ][::-1],
        set_aside=cards.Princess(),
    )
    game_round = Round(2, deck=deck)
    player0, player1 = game_round.players

    game_round.start(first_player=player0)
    assert tuple(map(CardType, player0.hand)) == (CardType.PRINCE, CardType.HANDMAID)
    assert tuple(map(CardType, player1.hand)) == (CardType.COUNTESS,)
    assert max(game_round.players, key=lambda p: p.hand.card.value) is player1

    (immunity,) = play_with_choices(player0, CardType.HANDMAID)
    assert immunity.player is player0
    game_round.advance_turn()

    results = play_with_choices(player1, CardType.PRIEST, move.OpponentChoice.NO_TARGET)
    assert results == ()
    game_round.advance_turn()

    discarded, dealt = play_with_choices(player0, CardType.PRINCE, player0)
    assert CardType(discarded.discarded) == CardType.GUARD
    assert CardType(dealt.dealt) == CardType.PRINCESS
    end = game_round.advance_turn()

    assert end.type == RoundState.Type.ROUND_END
    assert max(game_round.players, key=lambda p: p.hand.card.value) is player0
    assert end.winner is player0


def test_2_threeway_draw():
    """
    Three players end with a Guard and total discarded value of 2.

    player0 plays: Spy, Priest
    player1 plays: Guard, Guard
    player2 plays: Priest, Spy
    """
    game_round = make_round_from_player_cards(
        [cards.Spy(), cards.Priest(), cards.Guard()],
        [cards.Guard(), cards.Guard(), cards.Guard()],
        [cards.Priest(), cards.Spy(), cards.Guard()],
    )
    player0, player1, player2 = game_round.players
    game_round.start(first_player=player0)

    play_with_choices(player0, CardType.SPY)
    game_round.advance_turn()

    play_with_choices(player1, CardType.GUARD, player0, CardType.PRINCESS)
    game_round.advance_turn()

    play_with_choices(player2, CardType.PRIEST, player0)
    game_round.advance_turn()

    play_with_choices(player0, CardType.PRIEST, player1)
    game_round.advance_turn()

    play_with_choices(player1, CardType.GUARD, player2, CardType.PRINCESS)
    game_round.advance_turn()

    play_with_choices(player2, CardType.SPY)
    end = game_round.advance_turn()

    assert end.type == RoundState.Type.ROUND_END
    assert end.winners == {player0, player1, player2}
