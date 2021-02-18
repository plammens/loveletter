import itertools as itt
import unittest.mock

import pytest  # noqa
import pytest_cases  # noqa
import valid8

# from ... import * imports are needed because of how fixtures are generated;
# see pytest-cases#174
import loveletter.move
import loveletter.round
from loveletter import cards
from loveletter.cardpile import Deck, STANDARD_DECK_COUNTS
from loveletter.gameevent import GameInputRequest
from loveletter.gamenode import GameNodeState
from loveletter.round import RoundState, Turn
from loveletter.utils.misc import cycle_from
from test_loveletter.unit.test_cards_cases import *
from test_loveletter.unit.test_player_cases import *
from test_loveletter.unit.test_round_cases import INVALID_NUM_PLAYERS, VALID_NUM_PLAYERS
from test_loveletter.utils import (
    autofill_step,
    force_next_turn,
    give_card,
    play_card,
    play_mock_move,
    send_gracious,
)


@pytest.mark.parametrize("num_players", VALID_NUM_PLAYERS)
def test_newRound_validNumPlayers_works(num_players: int):
    game_round = Round(num_players=num_players)
    assert len(game_round.players) == num_players
    assert len(set(map(id, game_round.players))) == num_players
    assert all(player.round is game_round for player in game_round.players)
    assert all(game_round.players[i].id == i for i in range(num_players))
    assert not game_round.started
    assert game_round.state.type == RoundState.Type.INIT


@pytest.mark.parametrize("num_players", INVALID_NUM_PLAYERS)
def test_newRound_invalidNumPlayers_raises(num_players):
    with pytest.raises(valid8.ValidationError):
        Round(num_players)


@pytest.mark.parametrize("num_players", VALID_NUM_PLAYERS)
def test_newRound_validNumPlayers_hasStandardDeck(num_players: int):
    game_round = Round(num_players=num_players)
    assert game_round.deck.get_counts() == STANDARD_DECK_COUNTS


@pytest_cases.parametrize(first=[None, 0, 1, 3])
def test_start_newRound_setsCorrectGameState(new_round: Round, first):
    first = None if first is None else new_round.players[first % new_round.num_players]
    assert new_round.current_player is None

    new_round.start(first_player=first)
    assert new_round.current_player in new_round.players
    if first is not None:
        assert new_round.current_player is first
    assert new_round.started
    assert new_round.state.type == RoundState.Type.TURN
    # noinspection PyTypeChecker
    turn: Turn = new_round.state
    assert turn.current_player == new_round.current_player
    assert turn.turn_no == 1


@pytest_cases.parametrize(first=[0, 1, 3])
def test_start_withFirstPlayer_dealsCardsInOrder(new_round: Round, first):
    first = None if first is None else new_round.players[first % new_round.num_players]
    top_cards = new_round.deck.stack[-(new_round.num_players + 1) :]

    new_round.start(first_player=first)
    for player, card in zip(
        cycle_from(new_round.players, item=first), reversed(top_cards)
    ):
        assert card in player.hand


def test_start_newRound_dealsCardsCorrectly(new_round: Round):
    init_deck = list(new_round.deck)
    assert all(player.hand.card is None for player in new_round.players)
    new_round.start()
    # +1 is for extra card dealt to first player
    expected_cards_dealt = new_round.num_players + 1
    hands = list(itt.chain.from_iterable(p.hand for p in new_round.players))
    assert set(hands) == set(init_deck[-expected_cards_dealt:])
    assert list(new_round.deck) == init_deck[:-expected_cards_dealt]
    assert new_round.state.current_player == new_round.current_player


def test_start_insufficientCardsInDeck_raises(new_round: Round):
    new_round.deck = Deck([cards.Guard() for _ in new_round.players], None)
    with pytest.raises(valid8.ValidationError):
        new_round.start()


def test_start_emptyDeckUponStart_raises(new_round: Round):
    new_round.deck = Deck(
        [cards.Guard() for _ in range(new_round.num_players + 1)],
        set_aside=cards.Princess(),
    )
    with pytest.raises(valid8.ValidationError):
        new_round.start()


def test_currentPlayer_isValid(started_round):
    assert started_round.current_player.alive


def test_nextTurn_currentPlayerIsValid(started_round: Round):
    before = started_round.current_player
    play_mock_move(before)
    started_round.advance_turn()
    after = started_round.current_player
    assert after.alive
    assert after is not before


def test_nextTurn_dealsCard(started_round: Round):
    next_player = started_round.next_player(started_round.current_player)
    with unittest.mock.patch.object(started_round, "deal_card") as mock:
        force_next_turn(started_round)
        mock.assert_called_once_with(next_player)


def test_nextTurn_ongoingRound_roundStateIsTurn(started_round):
    play_mock_move(started_round.current_player)
    state = started_round.advance_turn()
    assert state.type == RoundState.Type.TURN
    assert isinstance(state, loveletter.round.Turn)


def test_nextTurn_onlyOnePlayerRemains_roundStateIsEnd(started_round):
    winner = started_round.players[-1]
    for player in started_round.players:
        if player is not winner:
            player.eliminate()
    state = force_next_turn(started_round)
    assert state.type == RoundState.Type.ROUND_END
    assert started_round.ended
    assert state.winner is winner


def test_chooseCardToPlay_validatesCardInHand(current_player: RoundPlayer):
    event = loveletter.round.ChooseCardToPlay(current_player)
    with pytest.raises(valid8.ValidationError):
        event.choice = cards.Guard()  # this card object is not in the player's hand


def test_chooseCardToPlay_checksMoveWithOtherCard(current_player: RoundPlayer):
    card_mock = CardMockCases.case_generic()
    give_card(current_player, card_mock)
    other_card = next(c for c in current_player.hand if c is not card_mock)

    event = loveletter.round.ChooseCardToPlay(current_player)
    event.choice = other_card
    card_mock.check_move.assert_called_once_with(current_player, other_card)


# noinspection PyTypeChecker
def test_advanceTurn_turnNoIncreases(started_round: Round):
    old_turn: Turn = started_round.state
    play_mock_move(started_round.current_player)
    new_turn: Turn = started_round.advance_turn()
    assert new_turn.turn_no == old_turn.turn_no + 1


@pytest_cases.parametrize_with_cases("set_aside", cases=CardMockCases)
def test_advanceTurn_emptyDeck_roundEndsWithLargestCardWinner(
    started_round: Round, set_aside
):
    started_round.deck = Deck([], set_aside=set_aside)
    increasing_cards = [cards.Guard(), cards.Priest(), cards.Baron(), cards.Princess()]
    for player, card in zip(started_round.players, increasing_cards):
        give_card(player, card, replace=True)
    # noinspection PyUnboundLocalVariable
    winner = player

    state = force_next_turn(started_round)
    assert state.type == RoundState.Type.ROUND_END
    assert state.winner is winner


@pytest_cases.parametrize_with_cases("from_player", cases=PlayerCases)
def test_roundEnd_cardTie_maxDiscardedValueWins(started_round: Round, from_player):
    discard_piles = (
        [cards.Priest(), cards.Prince()],  # total value: 7
        [cards.Guard(), cards.Countess()],  # total value: 8  -- best; offset=1
        [cards.Guard(), cards.Spy()],  # total value: 1
        [cards.Spy()],  # total value: 0
    )
    winner = started_round.get_player(from_player, offset=1)
    card = cards.Guard()

    started_round.deck.stack.clear()
    for player, discard_pile in zip(
        cycle_from(started_round.players, from_player, times=1),
        discard_piles,
    ):
        give_card(player, card, replace=True)
        player.discarded_cards = discard_pile

    end = force_next_turn(started_round)
    assert end.type == RoundState.Type.ROUND_END
    assert end.winner is winner


@pytest_cases.parametrize_with_cases("loser", cases=MaybePlayerCases)
def test_roundEnd_totalTie_everyoneWins(started_round: Round, loser):
    losers = {loser} if loser is not None else set()
    winners = set(started_round.players) - losers

    started_round.deck.stack.clear()
    for player in winners:
        give_card(player, cards.Princess(), replace=True)
        player.discarded_cards.clear()
    for loser in losers:
        give_card(loser, cards.Guard(), replace=True)

    end = force_next_turn(started_round)
    assert end.type == RoundState.Type.ROUND_END
    assert end.winners == winners
    if len(winners) > 1:
        with pytest.raises(valid8.ValidationError):
            # noinspection PyStatementEffect
            end.winner


def test_dealCard_newRound_playerInRound_works(new_round: Round):
    init_deck = list(new_round.deck)
    player = new_round.players[-1]
    assert player.hand.card is None
    card = new_round.deal_card(player)
    assert player.hand.card is card
    assert card is init_deck[-1]
    assert list(new_round.deck) == init_deck[:-1]


def test_dealCard_playerNotInRound_works(game_round: Round):
    other_round = Round(game_round.num_players)
    for player in other_round.players:
        with pytest.raises(valid8.ValidationError):
            game_round.deal_card(player)


def test_dealCard_playerInRound_addsToHand(started_round: Round):
    # pick non-current player (current player already has 2 cards in hand)
    player = started_round.next_player(started_round.current_player)
    before = set(player.hand)
    card = started_round.deal_card(player)
    after = set(player.hand)
    assert after == before | {card}
    assert (player.hand.card is card) == (len(before) == 0)


@pytest_cases.parametrize_with_cases("card", CardCases.MultiStepCases)
def test_nextTurn_ongoingMove_raises(started_round: Round, card: Card):
    player = started_round.current_player
    move = play_card(player, card, autofill=False)
    with pytest.raises(valid8.ValidationError):
        started_round.advance_turn()
    step = None
    for _ in card.steps:
        step = move.send(autofill_step(step))
        with pytest.raises(valid8.ValidationError):
            started_round.advance_turn()
    send_gracious(move, autofill_step(step))  # send final step
    started_round.advance_turn()


def test_nextPrevPlayer_matchesTurnDirection(started_round: Round):
    before = started_round.current_player
    force_next_turn(started_round)
    after = started_round.current_player
    assert started_round.next_player(before) is after
    assert started_round.previous_player(after) is before


def test_nextPlayer_deadPlayer_matchesTurnDirection(started_round: Round):
    before = started_round.current_player
    before.eliminate()
    force_next_turn(started_round)
    after = started_round.current_player or started_round.state.winner
    assert started_round.next_player(before) is after


def test_nextPlayer_deadPlayer_sameAsIfNotEliminated(started_round: Round):
    player = started_round.current_player
    next_while_living = started_round.next_player(player)
    player.eliminate()
    next_while_dead = started_round.next_player(player)
    assert next_while_living is next_while_dead


def test_nextPlayer_immediateNextDead_returnsLiving(started_round: Round):
    player = started_round.current_player
    victim = started_round.next_player(player)
    victim.eliminate()
    next_player = started_round.next_player(player)
    assert next_player is not victim
    assert next_player.alive


def test_prevPlayer_deadPlayer_matchesTurnDirection(started_round: Round):
    before = started_round.current_player
    force_next_turn(started_round)
    after = started_round.current_player or started_round.state.winner
    after.eliminate()
    assert started_round.previous_player(after) is before


def test_prevPlayer_deadPlayer_sameAsIfNotEliminated(started_round: Round):
    player = started_round.current_player
    prev_while_living = started_round.previous_player(player)
    player.eliminate()
    prev_while_dead = started_round.previous_player(player)
    assert prev_while_living is prev_while_dead


def test_prevPlayer_immediatePrevDead_returnsLiving(started_round: Round):
    player = started_round.current_player
    victim = started_round.previous_player(player)
    victim.eliminate()
    prev_player = started_round.previous_player(player)
    assert prev_player is not victim
    assert prev_player.alive


def test_eventGenerator_yieldsCorrectTypes(new_round: Round):
    round_generator = new_round.play()

    def is_round_start(e):
        return isinstance(e, RoundState) and e.type == RoundState.Type.TURN

    event = round_generator.send(None)
    # all input requests until the round starts
    while not is_round_start(event):
        assert isinstance(event, GameInputRequest)
        event = round_generator.send(autofill_step(event))

    # until the round ends, repeat: turn -> player move choice -> move steps -> results
    while True:
        # starts with turn event
        assert isinstance(event, loveletter.round.Turn)
        # next, the player's move choice
        event = next(round_generator)
        assert isinstance(event, loveletter.round.ChooseCardToPlay)
        event = round_generator.send(autofill_step(event))
        assert isinstance(event, loveletter.round.PlayingCard)

        # the whole move is wrapped in a StopIteration catcher because there are some
        # moves with 0 steps and 0 results
        try:
            # the move starts; move steps
            event = round_generator.send(autofill_step(event))
            while isinstance(event, loveletter.move.MoveStep):
                event = round_generator.send(autofill_step(event))
            # move has ended; move results
            while isinstance(event, loveletter.move.MoveResult):
                event = next(round_generator)
        except StopIteration as e:
            results = e.value
            break

    assert tuple(r.type for r in results) == (GameNodeState.Type.END,)
