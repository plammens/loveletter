import random

import pytest
import pytest_cases
import valid8

import loveletter.cards as cards
import loveletter.move
import test_loveletter.test_cards_cases as card_cases
import test_loveletter.test_player_cases as player_cases
from loveletter.cardpile import Deck
from loveletter.cards import CardType
from loveletter.player import Player
from loveletter.round import Round, Turn
from test_loveletter.utils import (
    assert_state_is_preserved,
    autofill_move,
    autofill_step,
    force_next_turn,
    give_card,
    make_mock_move,
    mock_player,
    play_card,
    play_card_with_cleanup,
    restart_turn,
    send_gracious,
)


def test_cards_have_unique_nonnegative_value():
    values = {t.value for t in CardType}
    assert len(values) == len(CardType)
    assert all(type(v) is int for v in values)
    assert all(v >= 0 for v in values)


@pytest_cases.parametrize_with_cases("card", cases=card_cases.CardCases)
@pytest_cases.parametrize_with_cases(
    "player", cases=player_cases.DummyPlayerCases().case_single_card
)
def test_cardSteps_correspondsToReality(player: Player, card: cards.Card):
    move = play_card(player, card, autofill=False)
    step = None
    for expected_step_type in card.steps:
        step = move.send(autofill_step(step))
        assert type(step) == expected_step_type
    results = send_gracious(move, autofill_step(step))
    assert loveletter.move.is_move_results(results)


def test_spy_noOnePlayed_noOneGetsPoint(started_round: Round):
    for player in started_round.players[1:]:
        player.eliminate()
    force_next_turn(started_round)
    assert cards.Spy.collect_extra_points(started_round) == {}


def test_spy_onePlayed_getsPoint(started_round: Round):
    first = started_round.current_player
    play_card(first, cards.Spy())
    for player in started_round.players:
        if player is not first:
            player.eliminate()
    started_round.advance_turn()
    assert cards.Spy.collect_extra_points(started_round) == {first: 1}


def test_spy_onePlayedTwice_getsOnePoint(started_round: Round):
    first = started_round.current_player
    play_card(first, cards.Spy())
    restart_turn(started_round)
    play_card(first, cards.Spy())
    for player in started_round.players:
        if player is not first:
            player.eliminate()
    started_round.advance_turn()
    assert cards.Spy.collect_extra_points(started_round) == {first: 1}


def test_spy_onePlayed_doesNotGetPointIfDead(started_round: Round):
    first = started_round.current_player
    second = started_round.next_player(first)
    play_card(first, cards.Spy())
    for player in started_round.players:
        if player is not second:
            player.eliminate()
    started_round.advance_turn()
    assert cards.Spy.collect_extra_points(started_round) == {}


def test_spy_twoPlayed_noOneGetsPoint(started_round: Round):
    first = started_round.current_player
    second = started_round.next_player(first)
    play_card(first, cards.Spy())
    started_round.advance_turn()
    play_card(second, cards.Spy())
    for player in started_round.players[1:]:
        player.eliminate()
    started_round.advance_turn()
    assert cards.Spy.collect_extra_points(started_round) == {}


def test_guard_correctGuess_eliminatesOpponent(started_round: Round):
    player = started_round.current_player
    for other in set(started_round.players) - {player}:
        assert other.alive
        move = play_card(player, cards.Guard())
        target_step = move.send(None)
        target_step.choice = other
        guess_step = move.send(target_step)
        guess_step.choice = type(other.hand.card)
        send_gracious(move, guess_step)
        assert not other.alive
        # artificially start new turn with same player
        started_round.state = Turn(player)


def test_guard_incorrectGuess_doesNotEliminateOpponent(started_round: Round):
    player = started_round.current_player
    for other in set(started_round.players) - {player}:
        assert other.alive
        for wrong_type in set(CardType) - {CardType(type(other.hand.card))}:
            move = play_card(player, cards.Guard())
            target_step = next(move)
            target_step.choice = other
            guess_step = move.send(target_step)
            guess_step.choice = wrong_type
            send_gracious(move, guess_step)
            assert other.alive
            # artificially start new turn with same player
            started_round.state = Turn(player)


def test_priest_validOpponent_showsCard(started_round: Round):
    player = started_round.current_player
    opponent = started_round.next_player(player)
    move = play_card(player, cards.Priest())
    target_step = next(move)
    target_step.choice = opponent
    result, *_ = send_gracious(move, target_step)
    assert len(_) == 0
    assert isinstance(result, loveletter.move.ShowOpponentCard)
    move.close()
    assert result.opponent is opponent


@pytest_cases.parametrize_with_cases(
    "card1,card2", cases=card_cases.CardPairCases().case_ordered_pair
)
def test_baron_weakerOpponent_opponentEliminated(started_round: Round, card1, card2):
    player = started_round.current_player
    opponent = started_round.next_player(player)
    give_card(player, card2, replace=True)
    give_card(opponent, card1, replace=True)

    move = play_card(player, cards.Baron())
    target_step = next(move)
    target_step.choice = opponent
    comparison, elimination, *_ = send_gracious(move, target_step)
    move.close()
    assert len(_) == 0
    assert isinstance(comparison, loveletter.move.CardComparison)
    assert isinstance(elimination, loveletter.move.PlayerEliminated)
    assert comparison.opponent is opponent
    assert elimination.eliminated is opponent

    assert player.alive
    assert not opponent.alive
    # TODO: mock checks for .eliminate()


@pytest_cases.parametrize_with_cases(
    "card1,card2", cases=card_cases.CardPairCases().case_ordered_pair
)
def test_baron_strongerOpponent_selfEliminated(started_round: Round, card1, card2):
    player = started_round.current_player
    opponent = started_round.next_player(player)
    give_card(player, card1, replace=True)
    give_card(opponent, card2, replace=True)

    move = play_card(player, cards.Baron())
    target_step = next(move)
    target_step.choice = opponent
    comparison, elimination, *_ = send_gracious(move, target_step)
    move.close()
    assert len(_) == 0
    assert isinstance(comparison, loveletter.move.CardComparison)
    assert isinstance(elimination, loveletter.move.PlayerEliminated)
    assert comparison.opponent is opponent
    assert elimination.eliminated is player

    assert not player.alive
    assert opponent.alive


@pytest_cases.parametrize_with_cases("card", cases=card_cases.CardCases)
def test_baron_equalOpponent_noneEliminated(started_round: Round, card):
    player = started_round.current_player
    opponent = started_round.next_player(player)
    give_card(player, card, replace=True)
    give_card(opponent, card, replace=True)

    move = play_card(player, cards.Baron())
    target_step = next(move)
    target_step.choice = opponent
    comparison, *_ = send_gracious(move, target_step)
    move.close()
    assert len(_) == 0
    assert isinstance(comparison, loveletter.move.CardComparison)

    assert player.alive
    assert opponent.alive


def test_handmaid_playerBecomesImmune(current_player: Player):
    assert not current_player.immune
    results = play_card(current_player, cards.Handmaid())
    assert tuple(map(type, results)) == (loveletter.move.ImmunityGranted,)
    assert results[0].player is current_player
    assert current_player.immune


@pytest_cases.parametrize_with_cases("card", card_cases.case_target_card)
def test_targetCard_againstImmunePlayer_raises(started_round: Round, card):
    immune_player = started_round.current_player
    play_card(immune_player, cards.Handmaid())
    # should be immune now
    started_round.advance_turn()
    opponent = started_round.current_player
    with play_card_with_cleanup(opponent, card) as move:
        target_step = next(move)
        with pytest.raises(valid8.ValidationError):
            target_step.choice = immune_player
            move.send(target_step)


def test_handmaid_immunityLastsOneFullRotation(started_round: Round):
    immune_player = started_round.current_player
    play_card(immune_player, cards.Handmaid())
    started_round.advance_turn()
    while (current := started_round.current_player) is not immune_player:
        assert immune_player.immune
        make_mock_move(current)
        started_round.advance_turn()
    assert not immune_player.immune


def test_handmaid_immunityLastsOneFullRotation_withDeaths(started_round: Round):
    immune_player = started_round.current_player
    play_card(immune_player, cards.Handmaid())
    started_round.advance_turn()
    killer = started_round.current_player
    for player in set(started_round.players) - {immune_player, killer}:
        assert immune_player.immune
        player.eliminate()
    assert immune_player.immune
    force_next_turn(started_round)
    assert not immune_player.immune


@pytest_cases.parametrize("card_type", set(CardType) - {CardType.PRINCESS})
@pytest_cases.parametrize_with_cases("target", cases=player_cases.PlayerCases)
def test_prince_againstNonPrincess_dealsCard(
    started_round: Round, target: Player, card_type
):
    player = started_round.current_player
    give_card(target, card_type.card_class(), replace=True)
    target_card = target.hand.card

    deck_before = list(started_round.deck)
    move = play_card(player, cards.Prince())
    target_step = next(move)
    target_step.choice = target
    results = send_gracious(move, target_step)
    assert tuple(map(type, results)) == (
        loveletter.move.CardDiscarded,
        loveletter.move.CardDealt,
    )
    assert results[0].target is target
    assert target.alive
    assert target.hand.card is deck_before[-1]
    assert target.cards_played[-1 if target is not player else -2] is target_card
    # Checking second-to-last as last is the Prince card:
    assert list(started_round.discard_pile)[-2] is target_card
    assert list(started_round.deck) == deck_before[:-1]


def test_prince_againstPrincess_kills(started_round: Round):
    player = started_round.current_player
    victim = started_round.next_player(player)
    give_card(victim, cards.Princess(), replace=True)
    victim_card = victim.hand.card

    deck_before = list(started_round.deck)
    move = play_card(player, cards.Prince())
    target_step = next(move)
    target_step.choice = victim
    results = send_gracious(move, target_step)
    assert tuple(map(type, results)) == (
        loveletter.move.CardDiscarded,
        loveletter.move.PlayerEliminated,
    )
    assert results[0].target is victim
    assert results[0].discarded is victim_card
    assert results[1].eliminated is victim
    assert not victim.alive
    assert victim.cards_played[-1].value == CardType.PRINCESS
    assert list(started_round.deck) == deck_before


@pytest_cases.parametrize_with_cases("target", cases=player_cases.PlayerCases)
def test_prince_emptyDeck_dealsSetAsideCard(current_player: Player, target: Player):
    set_aside = card_cases.CardMockCases().case_generic()
    current_player.round.deck = Deck([], set_aside=set_aside)

    give_card(target, card_cases.CardMockCases().case_generic(), replace=True)
    move = play_card(current_player, cards.Prince())
    target_step = next(move)
    target_step.choice = target
    send_gracious(move, target_step)
    assert target.hand.card is set_aside
    assert current_player.round.deck.set_aside is None
    assert not current_player.round.deck


def test_chancellor_correctlyHandlesCards(started_round):
    player = started_round.current_player
    other_card = player.hand.card
    top_2 = started_round.deck.stack[-2:]

    move = play_card(player, cards.Chancellor())
    card_choice: loveletter.move.ChooseOneCard = next(move)
    assert player.hand.card is other_card
    assert other_card in card_choice.options
    assert set(top_2).issubset(set(card_choice.options))

    card_choice.choice = random.choice(card_choice.options)
    order_choice: loveletter.move.ChooseOrderForDeckBottom = move.send(card_choice)
    assert player.hand.card is card_choice.choice
    assert len(player.hand) == 1
    assert set(card_choice.options) - {card_choice.choice} == set(order_choice.cards)

    order = list(order_choice.cards)
    random.shuffle(order)
    order_choice.choice = tuple(order)
    results = send_gracious(move, order_choice)
    assert started_round.deck.stack[:2] == order

    assert tuple(map(type, results)) == (
        loveletter.move.CardChosen,
        loveletter.move.CardsPlacedBottomOfDeck,
    )
    assert results[0].choice is card_choice.choice
    assert results[1].cards == order_choice.choice


def test_chancellor_oneCardInDeck_onlyUsesOneCard(started_round: Round):
    deck_card, set_aside = cards.Spy(), cards.Princess()
    started_round.deck = Deck([deck_card], set_aside=set_aside)
    player = started_round.current_player
    move = play_card(player, cards.Chancellor())
    card_choice = next(move)
    assert len(card_choice.options) == 2
    assert set(card_choice.options) == {player.hand.card, deck_card}
    assert started_round.deck.set_aside is set_aside

    # cleanup to avoid exception when .close() is called
    autofill_move(move, start_step=card_choice)


def test_chancellor_cancelAfterStart_raises(current_player: Player):
    chancellor = cards.Chancellor()
    move = play_card(current_player, chancellor)
    with assert_state_is_preserved(current_player.round):
        next(move)
        # player has already seen cards so shouldn't be able to cancel:
        assert not chancellor.cancellable
        with pytest.raises(loveletter.move.CancellationError):
            move.throw(loveletter.move.CancelMove)
        assert current_player.round.state.stage == Turn.Stage.INVALID


@pytest_cases.parametrize("card_type", set(CardType) - {CardType.PRINCE, CardType.KING})
def test_countess_playNotPrinceOrKing_noOp(current_player: Player, card_type):
    target = current_player.round.next_player(current_player)
    with assert_state_is_preserved(
        current_player.round, allow_mutation={current_player, target}
    ) as mocked_round:
        player, target = mocked_round.current_player, mocked_round.players[target.id]
        give_card(player, cards.Countess(), replace=True)
        move = play_card(player, card := card_type.card_class(), autofill=False)
        step = None
        for _ in card.steps:
            step = move.send(step)
            if isinstance(step, loveletter.move.PlayerChoice):
                step.choice = target
            else:
                step = autofill_step(step)
        send_gracious(move, step)


@pytest_cases.parametrize("card_type", {CardType.PRINCE, CardType.KING})
def test_countess_playPrinceOrKing_raises(current_player: Player, card_type):
    give_card(current_player, cards.Countess(), replace=True)
    give_card(current_player, card := card_type.card_class())
    with assert_state_is_preserved(current_player.round) as mocked_round:
        with pytest.raises(valid8.ValidationError):
            autofill_move(mocked_round.current_player.play_card(card))


def test_princess_eliminatesSelf(current_player: Player):
    player_mock = mock_player(current_player)
    play_card(player_mock, cards.Princess())
    player_mock.eliminate.assert_called_once()
    assert not current_player.alive


@pytest_cases.parametrize_with_cases("card", cases=card_cases.case_target_card)
def test_targetCard_chooseSelf_raises(current_player, card):
    with play_card_with_cleanup(current_player, card) as move:
        target_step = next(move)
        with pytest.raises(valid8.ValidationError):
            target_step.choice = current_player
            move.send(target_step)
