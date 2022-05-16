import random

import pytest  # noqa
import pytest_cases  # noqa
import valid8

# from ... import * imports are needed because of how fixtures are generated;
# see pytest-cases#174
import loveletter
import loveletter.cards as cards
from loveletter.cardpile import Deck
from loveletter.cards import CardType  # noqa
from loveletter.round import Round, Turn  # noqa
from loveletter.roundplayer import RoundPlayer  # noqa
from test_loveletter.unit.test_cards_cases import *
from test_loveletter.unit.test_player_cases import *
from test_loveletter.utils import (
    assert_state_is_preserved,
    autofill_move,
    autofill_step,
    card_from_card_type,
    force_end_round,
    force_next_turn,
    give_card,
    mock_player,
    play_card,
    play_card_with_cleanup,
    play_mock_move,
    restart_turn,
    send_gracious,
)


@pytest_cases.parametrize(card_type=CardType)
def test_cardType_hasNonnegativeValue(card_type):
    value = card_type.card_class.value
    assert type(value) is int
    assert value >= 0


@pytest_cases.parametrize(card_type=CardType)
def test_cardType_hasDescription(card_type):
    cls = card_type.card_class
    assert hasattr(cls, "description")
    description = cls.description
    assert isinstance(description, str)
    assert description[0].isupper()
    assert description.endswith(".")


@pytest_cases.parametrize(card_type=card_cases.ALL_TYPES)
def test_cardType_any_isLeqPrincess(card_type):
    assert card_type <= CardType.PRINCESS


@pytest_cases.parametrize_with_cases(
    "card1,card2", cases=CardPairCases.case_ordered_pair
)
def test_cardTypeOrder_increasingPair_asExpected(card1, card2):
    assert CardType(card1) < CardType(card2)


@pytest_cases.parametrize(card_type=card_cases.ALL_TYPES)
def test_cardType_fromIdenticalSubclass_works(card_type):
    assert CardType(card_type.card_class) == card_type


@pytest_cases.parametrize(card_type=card_cases.ALL_TYPES)
def test_cardType_fromSubclass_works(card_type):
    class DummySubclass(card_type.card_class):
        pass

    assert CardType(DummySubclass) == card_type


@pytest_cases.parametrize(value=[0, 2, 9])
def test_cardType_fromIntValue_raises(value):
    with pytest.raises(ValueError):
        CardType(value)


@pytest_cases.parametrize_with_cases("card", cases=CardCases)
@pytest_cases.parametrize_with_cases("player", cases=DummyPlayerCases.case_single_card)
def test_cardSteps_correspondsToReality(player: RoundPlayer, card: cards.Card):
    move = play_card(player, card, autofill=False)
    step = None
    for expected_step_type in card.steps:
        step = move.send(autofill_step(step))
        assert type(step) == expected_step_type
    results = send_gracious(move, autofill_step(step))
    assert mv.is_move_results(results)


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


def test_spy_oneDiscarded_getsPoint(started_round: Round):
    first = started_round.current_player
    second = started_round.next_player(first)

    give_card(second, cards.Spy(), replace=True)
    move = play_card(first, cards.Prince())
    target_step = next(move)
    target_step.choice = second
    send_gracious(move, target_step)

    for player in started_round.players:
        if player is not second:
            player.eliminate()
    started_round.advance_turn()
    assert cards.Spy.collect_extra_points(started_round) == {second: 1}


def test_spy_onePlayedTwice_getsOnePoint(started_round: Round):
    first = started_round.current_player
    play_card(first, cards.Spy())
    restart_turn(started_round)
    play_card(first, cards.Spy())
    force_end_round(started_round)
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
    force_end_round(started_round)
    assert cards.Spy.collect_extra_points(started_round) == {}


def test_spy_twoPlayedOneDead_aliveGetsPoint(started_round: Round):
    first = started_round.current_player
    second = started_round.next_player(first)
    play_card(first, cards.Spy())
    started_round.advance_turn()
    play_card(second, cards.Spy())
    started_round.advance_turn()

    second.eliminate()
    force_end_round(started_round)

    assert cards.Spy.collect_extra_points(started_round) == {first: 1}


def test_guard_guessGuard_raises(started_round: Round):
    player = started_round.current_player
    move = play_card(player, cards.Guard())
    target_step = next(move)
    guess_step = move.send(autofill_step(target_step))
    with pytest.raises(valid8.ValidationError):
        guess_step.choice = CardType.GUARD


def test_guard_correctGuess_eliminatesOpponent(started_round: Round):
    player = started_round.current_player
    for other in set(started_round.players) - {player}:
        assert other.alive
        move = play_card(player, cards.Guard())
        target_step = move.send(None)
        target_step.choice = other
        guess_step = move.send(target_step)

        card_type = type(other.hand.card)
        guess = card_type if card_type != cards.Guard else cards.Spy
        guess_step.choice = guess
        results = send_gracious(move, guess_step)
        if card_type != cards.Guard:
            assert tuple(map(type, results)) == (
                mv.CorrectCardGuess,
                mv.PlayerEliminated,
            )
            assert results[0].guess == CardType(guess)
            assert results[1].eliminated == other
            assert not other.alive

        # artificially start new turn with same player
        restart_turn(started_round)


def test_guard_incorrectGuess_doesNotEliminateOpponent(started_round: Round):
    player = started_round.current_player
    for other in set(started_round.players) - {player}:
        assert other.alive
        wrong_guesses = set(CardType) - {
            CardType(type(other.hand.card)),
            CardType.GUARD,
        }
        for guess in wrong_guesses:
            move = play_card(player, cards.Guard())
            target_step = next(move)
            target_step.choice = other
            guess_step = move.send(target_step)
            guess_step.choice = guess
            results = send_gracious(move, guess_step)
            assert tuple(map(type, results)) == (mv.WrongCardGuess,)
            assert results[0].guess == CardType(guess)
            assert other.alive
            # artificially start new turn with same player
            restart_turn(started_round)


def test_priest_validOpponent_showsCard(started_round: Round):
    player = started_round.current_player
    opponent = started_round.next_player(player)
    move = play_card(player, cards.Priest())
    target_step = next(move)
    target_step.choice = opponent
    result, *_ = send_gracious(move, target_step)
    assert len(_) == 0
    assert isinstance(result, mv.ShowOpponentCard)
    move.close()
    assert result.opponent is opponent


@pytest_cases.parametrize_with_cases(
    "card1,card2", cases=CardPairCases.case_ordered_pair
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
    assert isinstance(comparison, mv.CardComparison)
    assert isinstance(elimination, mv.PlayerEliminated)
    assert comparison.opponent is opponent
    assert elimination.eliminated is opponent

    assert player.alive
    assert not opponent.alive
    # TODO: mock checks for .eliminate()


@pytest_cases.parametrize_with_cases(
    "card1,card2", cases=CardPairCases.case_ordered_pair
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
    assert isinstance(comparison, mv.CardComparison)
    assert isinstance(elimination, mv.PlayerEliminated)
    assert comparison.opponent is opponent
    assert elimination.eliminated is player

    assert not player.alive
    assert opponent.alive


@pytest_cases.parametrize_with_cases("card", cases=CardCases)
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
    assert isinstance(comparison, mv.CardComparison)

    assert player.alive
    assert opponent.alive


def test_handmaid_playerBecomesImmune(current_player: RoundPlayer):
    assert not current_player.immune
    results = play_card(current_player, cards.Handmaid())
    assert tuple(map(type, results)) == (mv.ImmunityGranted,)
    assert results[0].player is current_player
    assert current_player.immune


@pytest_cases.parametrize_with_cases("card", CardCases.MultiStepCases.TargetCases)
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
        play_mock_move(current)
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
@pytest_cases.parametrize_with_cases("target", cases=PlayerCases)
def test_prince_againstNonPrincess_dealsCard(
    started_round: Round, target: RoundPlayer, card_type
):
    player = started_round.current_player
    give_card(target, card_from_card_type(card_type), replace=True)
    target_card = target.hand.card

    deck_before = list(started_round.deck)
    move = play_card(player, cards.Prince())
    target_step = next(move)
    target_step.choice = target
    results = send_gracious(move, target_step)
    assert tuple(map(type, results)) == (
        mv.CardDiscarded,
        mv.CardDealt,
    )
    assert results[0].target is target
    assert target.alive
    assert target.hand.card is deck_before[-1]
    assert target.discarded_cards[-1 if target is not player else -2] is target_card
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
        mv.CardDiscarded,
        mv.PlayerEliminated,
    )
    assert results[0].target is victim
    assert results[0].discarded is victim_card
    assert results[1].eliminated is victim
    assert not victim.alive
    assert CardType(victim.discarded_cards[-1]) == CardType.PRINCESS
    assert list(started_round.deck) == deck_before


@pytest_cases.parametrize_with_cases("target", cases=PlayerCases)
@pytest_cases.parametrize_with_cases("set_aside", cases=CardMockCases)
def test_prince_emptyDeck_dealsSetAsideCard(
    current_player: RoundPlayer, target: RoundPlayer, set_aside: cards.Card
):
    current_player.round.deck = Deck([], set_aside=set_aside)

    give_card(target, CardMockCases().case_generic(), replace=True)
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
    card_choice: mv.ChooseOneCard = next(move)
    assert player.hand.card is other_card
    assert other_card in card_choice.options
    assert set(top_2).issubset(set(card_choice.options))

    card_choice.choice = random.choice(card_choice.options)
    order_choice: mv.ChooseOrderForDeckBottom = move.send(card_choice)
    assert player.hand.card is card_choice.choice
    assert len(player.hand) == 1
    assert set(card_choice.options) - {card_choice.choice} == set(order_choice.cards)

    order = list(order_choice.cards)
    random.shuffle(order)
    order_choice.choice = tuple(order)
    results = send_gracious(move, order_choice)
    assert started_round.deck.stack[:2] == order

    assert tuple(map(type, results)) == (
        mv.CardChosen,
        mv.CardsPlacedBottomOfDeck,
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


def test_chancellor_cancelAfterStart_raises(current_player: RoundPlayer):
    chancellor = cards.Chancellor()
    move = play_card(current_player, chancellor)
    with assert_state_is_preserved(current_player.round):
        next(move)
        # player has already seen cards so shouldn't be able to cancel:
        assert not chancellor.cancellable
        with pytest.raises(mv.CancellationError):
            move.throw(mv.CancelMove)
        assert current_player.round.state.stage == Turn.Stage.INVALID


def test_king_againstOpponent_swapsCards(current_player: RoundPlayer):
    move = play_card(current_player, cards.King())
    target_step = autofill_step(next(move))
    target = target_step.choice
    player_card, target_card = current_player.hand.card, target.hand.card

    results = send_gracious(move, target_step)
    assert current_player.hand.card is target_card
    assert target.hand.card is player_card
    assert tuple(map(type, results)) == (mv.CardsSwapped,)
    assert results[0].opponent is target


@pytest_cases.parametrize("card_type", set(CardType) - {CardType.PRINCE, CardType.KING})
def test_countess_playNotPrinceOrKing_noOp(current_player: RoundPlayer, card_type):
    target = current_player.round.next_player(current_player)
    with assert_state_is_preserved(
        current_player.round, allow_mutation={current_player, target}
    ) as mocked_round:
        player, target = mocked_round.current_player, mocked_round.players[target.id]
        give_card(player, cards.Countess(), replace=True)
        move = play_card(player, card := card_from_card_type(card_type), autofill=False)
        step = None
        for _ in card.steps:
            step = move.send(step)
            if isinstance(step, mv.PlayerChoice):
                step.choice = target
            else:
                step = autofill_step(step)
        send_gracious(move, step)


@pytest_cases.parametrize("other_card_type", {CardType.PRINCE, CardType.KING})
def test_countess_choosePrinceOrKing_raises(current_player, other_card_type):
    give_card(current_player, cards.Countess(), replace=True)
    give_card(current_player, other_card := card_from_card_type(other_card_type))

    event = loveletter.round.ChooseCardToPlay(current_player)
    with pytest.raises(valid8.ValidationError):
        event.choice = other_card


@pytest_cases.parametrize("other_card_type", {CardType.PRINCE, CardType.KING})
def test_countess_playPrinceOrKing_raises(current_player, other_card_type):
    give_card(current_player, cards.Countess(), replace=True)
    give_card(current_player, card := card_from_card_type(other_card_type))

    with assert_state_is_preserved(current_player.round) as mocked_round:
        with pytest.raises(valid8.ValidationError):
            autofill_move(mocked_round.current_player.play_card(card))


def test_princess_eliminatesSelf(current_player: RoundPlayer):
    player_mock = mock_player(current_player)
    play_card(player_mock, cards.Princess())
    player_mock.eliminate.assert_called_once()
    assert not current_player.alive


@pytest_cases.parametrize_with_cases("card", cases=CardCases.MultiStepCases.TargetCases)
def test_targetCard_chooseSelf_raises(current_player, card):
    with play_card_with_cleanup(current_player, card) as move:
        target_step = next(move)
        with pytest.raises(valid8.ValidationError):
            target_step.choice = current_player
            move.send(target_step)


@pytest_cases.parametrize_with_cases("card", cases=CardCases.MultiStepCases.TargetCases)
def test_targetCard_allOpponentsImmune_canChooseNone(started_round: Round, card):
    for player in started_round.players:
        if player is not started_round.current_player:
            player.immune = True

    with assert_state_is_preserved(
        started_round, allow_mutation={started_round.current_player}
    ) as mocked_round:
        move = play_card(mocked_round.current_player, card)
        target_step = next(move)
        target_step.choice = mv.OpponentChoice.NO_TARGET
        send_gracious(move, target_step)
