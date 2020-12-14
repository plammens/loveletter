import loveletter.cards as cards
import loveletter.move as move
from loveletter.cardpile import Deck
from loveletter.cards import CardType
from loveletter.round import Round, RoundState
from test_loveletter.utils import (
    make_round_from_player_cards,
    play_random_move,
    play_with_choices,
)


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

    results = play_with_choices(player1, CardType.PRIEST, move.OpponentChoice.NO_TARGET)
    assert results == ()

    discarded, dealt = play_with_choices(player0, CardType.PRINCE, player0)
    assert CardType(discarded.discarded) == CardType.GUARD
    assert CardType(dealt.dealt) == CardType.PRINCESS

    end = game_round.state
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
    play_with_choices(player1, CardType.GUARD, player0, CardType.PRINCESS)
    play_with_choices(player2, CardType.PRIEST, player0)
    play_with_choices(player0, CardType.PRIEST, player1)
    play_with_choices(player1, CardType.GUARD, player2, CardType.PRINCESS)
    play_with_choices(player2, CardType.SPY)

    end = game_round.state
    assert end.type == RoundState.Type.ROUND_END
    assert end.winners == {player0, player1, player2}


def test_3_king_win():
    """
    player1 draws the Princess but is forced to relinquish it because they have a King.
    """
    game_round = make_round_from_player_cards(
        [cards.Guard(), cards.Baron()],
        [cards.King(), cards.Princess()],
    )
    player0, player1 = game_round.players
    game_round.start(first_player=player0)

    play_with_choices(player0, CardType.GUARD, player1, cards.Princess)
    play_random_move(player1)

    end = game_round.state
    assert end.type == RoundState.Type.ROUND_END
    assert end.winner is player0


def test_4_princess_suicide():
    """
    player1 holds a Princess but has to eliminate themselves because they draw a Prince
    and the opponent is immune.
    """
    game_round = make_round_from_player_cards(
        [cards.Handmaid(), cards.Baron(), cards.Guard()],
        [cards.Princess(), cards.Prince(), cards.Countess()],
    )
    player0, player1 = game_round.players
    game_round.start(first_player=player0)

    play_with_choices(player0, CardType.HANDMAID)
    play_random_move(player1)

    assert game_round.ended
    assert game_round.state.winner is player0
    assert CardType(game_round.deck.take()) == CardType.GUARD  # assert no card dealt


def test_5_baron_suicide():
    """
    player0 has Baron-Baron and everyone else has higher cards, so they die.
    """
    game_round = make_round_from_player_cards(
        [cards.Baron(), cards.Baron()],
        [cards.Countess(), cards.Handmaid(), cards.Guard()],
        [cards.Handmaid(), cards.Princess(), cards.Guard()],
    )
    player0, player1, player2 = game_round.players
    game_round.start(first_player=player0)

    play_random_move(player0)
    assert not game_round.ended
    assert not player0.alive
    assert player1.alive
    assert player2.alive


def test_6_guard_win():
    """A chain of Guard eliminations that ends in player 3 winning"""
    game_round = make_round_from_player_cards(
        [cards.Countess(), cards.Guard()],
        [cards.Princess(), cards.Guard()],
        [cards.Guard(), cards.Guard()],
        [cards.King()],
    )
    player0, player1, player2, player3 = game_round.players
    game_round.start(first_player=player1)

    play_with_choices(player1, CardType.GUARD, player0, CardType.KING)
    play_with_choices(player2, CardType.GUARD, player1, CardType.COUNTESS)
    play_with_choices(player3, CardType.GUARD, player2, CardType.PRINCESS)

    assert game_round.ended
    assert not player0.alive
    assert not player1.alive
    assert not player2.alive
    assert player3.alive
    assert game_round.state.winner is player3
