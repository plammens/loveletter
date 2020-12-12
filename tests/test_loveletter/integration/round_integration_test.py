import loveletter.cards as cards
import loveletter.move as move
from loveletter.cardpile import Deck
from loveletter.cards import CardType
from loveletter.player import Player
from loveletter.round import Round, RoundState
from test_loveletter.utils import send_gracious


def play_with_choices(player: Player, card_type: CardType, *choices):
    move_ = player.play_type(card_type)
    step = None
    for choice in choices:
        step = move_.send(step)
        step.choice = choice
    return send_gracious(move_, step)


def test_1():
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
