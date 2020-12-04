import loveletter.cards as cards
from loveletter.round import Round
from test_loveletter.utils import autofill_moves, collect_card_classes


def test_cards_have_unique_nonnegative_value():
    classes = collect_card_classes()
    values = {cls.value for cls in classes}
    assert len(values) == len(classes)
    assert all(type(v) is int for v in values)
    assert all(v >= 0 for v in values)


def test_spy_noOnePlayed_noOneGetsPoint(started_round: Round):
    for player in started_round.players[1:]:
        player.eliminate()
    started_round.next_turn()
    assert cards.Spy.collect_extra_points(started_round) == {}


def test_spy_onePlayed_getsPoint(started_round: Round):
    first = started_round.current_player
    first.give(cards.Spy())
    autofill_moves(first.play_card("right"))
    for player in started_round.players:
        if player is not first:
            player.eliminate()
    started_round.next_turn()
    assert cards.Spy.collect_extra_points(started_round) == {first: 1}


def test_spy_onePlayed_getsPointEvenIfDead(started_round: Round):
    first = started_round.current_player
    second = started_round.players[(first.id + 1) % started_round.num_players]
    first.give(cards.Spy())
    autofill_moves(first.play_card("right"))
    for player in started_round.players:
        if player is not second:
            player.eliminate()
    started_round.next_turn()
    assert cards.Spy.collect_extra_points(started_round) == {first: 1}


def test_spy_twoPlayed_noOneGetsPoint(started_round: Round):
    first = started_round.current_player
    second = started_round.players[(first.id + 1) % started_round.num_players]
    first.give(cards.Spy())
    autofill_moves(first.play_card("right"))
    started_round.next_turn()
    second.give(cards.Spy())
    autofill_moves(second.play_card("right"))
    for player in started_round.players[1:]:
        player.eliminate()
    started_round.next_turn()
    assert cards.Spy.collect_extra_points(started_round) == {}
