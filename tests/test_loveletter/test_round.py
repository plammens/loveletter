import itertools
import unittest.mock

import pytest
import pytest_cases
import valid8

import test_loveletter.test_cards_cases as card_cases
from loveletter.cardpile import Deck, STANDARD_DECK_COUNTS
from loveletter.cards import Card
from loveletter.round import Round, RoundEnd, RoundState, Turn
from test_loveletter.test_round_cases import INVALID_NUM_PLAYERS, VALID_NUM_PLAYERS
from test_loveletter.utils import (
    autofill_step,
    force_next_turn,
    make_mock_move,
    play_card,
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
    assert game_round.deck == Deck.from_counts(STANDARD_DECK_COUNTS)


def test_start_newRound_setsCorrectGameState(new_round: Round):
    assert new_round.current_player is None
    new_round.start()
    assert new_round.current_player in new_round.players
    assert new_round.started
    assert new_round.state.type == RoundState.Type.TURN
    assert new_round.state.current_player == new_round.current_player


def test_start_newRound_dealsCardsCorrectly(new_round: Round):
    init_deck = list(new_round.deck)
    assert all(player.hand.card is None for player in new_round.players)
    new_round.start()
    # +1 is for extra card dealt to first player
    expected_cards_dealt = new_round.num_players + 1
    hands = list(itertools.chain.from_iterable(p.hand for p in new_round.players))
    assert set(hands) == set(init_deck[-expected_cards_dealt:])
    assert list(new_round.deck) == init_deck[:-expected_cards_dealt]
    assert new_round.state.current_player == new_round.current_player


def test_currentPlayer_isValid(started_round):
    assert started_round.current_player.alive


def test_nextTurn_currentPlayerIsValid(started_round: Round):
    before = started_round.current_player
    make_mock_move(before)
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
    make_mock_move(started_round.current_player)
    state = started_round.advance_turn()
    assert state.type == RoundState.Type.TURN
    assert isinstance(state, Turn)


def test_nextTurn_onlyOnePlayerRemains_roundStateIsEnd(started_round):
    winner = started_round.players[-1]
    for player in started_round.players:
        if player is not winner:
            player.eliminate()
    state = force_next_turn(started_round)
    assert state.type == RoundState.Type.ROUND_END
    assert started_round.ended
    assert isinstance(state, RoundEnd)
    assert state.winner is winner


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


@pytest_cases.parametrize_with_cases("card", card_cases.CardCases().case_multistep_card)
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
