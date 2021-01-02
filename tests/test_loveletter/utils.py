import collections
import contextlib
import copy
import functools
import math
import random
import unittest.mock
from typing import (
    Any,
    Collection,
    Counter,
    Generator,
    Sequence,
    Tuple,
    Union,
)
from unittest.mock import MagicMock, Mock, PropertyMock

import more_itertools as mitt
import pytest
from multimethod import multimethod

import loveletter.move as move
import loveletter.round
from loveletter import cards as cards
from loveletter.cardpile import Deck, STANDARD_DECK_COUNTS
from loveletter.cards import Card, CardType
from loveletter.gameevent import GameEvent, GameResultEvent
from loveletter.gamenode import EndState
from loveletter.round import Round, RoundState, Turn
from loveletter.roundplayer import RoundPlayer
from loveletter.utils import collect_subclasses  # noqa


def random_card_counts() -> Counter[CardType]:
    counts = collections.Counter(
        {
            card_type: random.randint(0, max_count)
            for card_type, max_count in STANDARD_DECK_COUNTS.items()
        }
    )
    # Remove classes with 0 count:
    for cls, count in tuple(counts.items()):
        if count == 0:
            del counts[cls]
    return counts


def autoplay_round(game_round: Round):
    if not game_round.started:
        game_round.start()
    while not game_round.ended:
        play_random_move(game_round.current_player)


def play_random_move(player):
    card = autofill_step(loveletter.round.PlayerMoveChoice(player)).choice
    autofill_move(player.play_card(card))
    player.round.advance_turn()


def autofill_move(
    move_: cards.MoveStepGenerator, start_step=None, num_steps: int = None, close=None
) -> Union[move.MoveStep, Tuple[move.MoveResult, ...]]:
    """
    Automatically play a move by making (arbitrary) choices for each of the steps.

    Useful if the test doesn't care about the specifics of the move, just wants to play
    it out.

    :param move_: Move step generator as returned by RoundPlayer.play().
    :param start_step: Starting step, if any. If not None, the caller will have already
                       completed part of the move, and this will be the most recent step
                       yielded by move_, from which autofill_move will pick up. If None,
                       it means start from the beginning.
    :param num_steps: Number of steps to complete. Steps will be completed until either
                      the move has been completed or the number of sent steps reaches
                      this number. None means no limit.
    :param close: Whether to call move_.close() at the end to make sure the generator
                  gets cleaned up. By default this will be true if num_steps is None.

    :return: The results of the move if it was played to completion, otherwise the most
             recent unfulfilled step yielded by ``move_``.
    """
    close = close if close is not None else (num_steps is None)
    max_steps = num_steps + 1 if num_steps is not None else math.inf
    i, step, results = 0, start_step, None
    try:
        while i < max_steps:
            step = move_.send(autofill_step(step))
            i += 1
    except StopIteration as e:
        results = e.value
    assert num_steps is None or i == max_steps
    if close:
        move_.close()
    return results if results is not None else step


@multimethod
def autofill_step(step: GameEvent):
    """Fulfill a step by making a(n arbitrary) choice"""
    raise TypeError(f"autofill_step not implemented for {type(step)}")


@autofill_step.register
def autofill_step(step: type(None)):
    # no-op for initial step
    return step


# noinspection PyUnusedLocal
@autofill_step.register
def autofill_step(step: GameResultEvent):
    # no-op for results
    return None


@autofill_step.register
def autofill_step(step: Mock):
    # special case for mocks
    return step


@autofill_step.register
def autofill_step(step: loveletter.round.FirstPlayerChoice):
    step.choice = random.choice(step.round.players)
    return step


@autofill_step.register
def autofill_step(step: loveletter.round.PlayerMoveChoice):
    hand = step.player.hand
    card_types = tuple(map(CardType, hand))
    if CardType.COUNTESS in card_types and (
        CardType.PRINCE in card_types or CardType.KING in card_types
    ):
        # we're forced to play the Countess
        step.choice = next(c for c in hand if CardType(c) == CardType.COUNTESS)
    else:
        step.choice = random.choice(list(hand))
    return step


@autofill_step.register
def autofill_step(step: move.PlayerChoice):
    options = [p for p in step.player.round.living_players if not p.immune]
    step.choice = random.choice(options)
    return step


@autofill_step.register
def autofill_step(step: move.OpponentChoice):
    game_round = step.player.round
    player = step.player
    players = set(game_round.living_players)
    opponents = players - {player} - {p for p in players if p.immune}
    step.choice = random.choice(list(opponents) or [move.OpponentChoice.NO_TARGET])
    return step


@autofill_step.register
def autofill_step(step: move.CardGuess):
    step.choice = random.choice(list(set(CardType) - {CardType.GUARD}))
    return step


@autofill_step.register
def autofill_step(step: move.ChooseOneCard):
    step.choice = random.choice(step.options)
    return step


@autofill_step.register
def autofill_step(step: move.ChooseOrderForDeckBottom):
    order = list(step.cards)
    random.shuffle(order)
    step.choice = tuple(order)
    return step


def play_mock_move(player):
    import test_loveletter.unit.test_cards_cases as card_cases

    card_mock = card_cases.CardMockCases().case_generic()
    play_card(player, card_mock, autofill=True)


def play_card(
    player: RoundPlayer, card: cards.Card, autofill=None, skip_if_disallowed=True
):
    from test_loveletter.unit.test_cards_cases import DISCARD_TYPES

    if autofill is None:
        autofill = CardType(card) in DISCARD_TYPES
    if (
        skip_if_disallowed
        and not isinstance(card, Mock)
        and CardType.COUNTESS in map(CardType, player.hand)
        and CardType(card) in {CardType.PRINCE, CardType.KING}
    ):
        pytest.skip(f"Playing {card} with Countess in hand will raise")

    give_card(player, card)
    move_ = player.play_card(card)
    if autofill:
        return autofill_move(move_, close=True)
    else:
        return move_


@contextlib.contextmanager
def play_card_with_cleanup(player: RoundPlayer, card: cards.Card):
    move_ = play_card(player, card, autofill=False)
    try:
        yield move_
    finally:
        try:
            move_.throw(move.CancelMove)
        except StopIteration:
            return
        except RuntimeError:
            move_.close()


def give_card(player: RoundPlayer, card: Card, replace=False):
    if replace:
        player.hand._cards.clear()
    elif len(player.hand) == 2:
        player.hand._cards.pop()
    player.give(card)


@contextlib.contextmanager
def assert_state_is_preserved(
    game_round: Round, allow_mutation: Collection[RoundPlayer] = (), with_mock=True
):
    state = game_round.state
    current_player = game_round.current_player
    round_copy = copy.deepcopy(game_round)
    # player cards should be a shallow copy:
    for player, player_copy in zip(game_round.players, round_copy.players):
        player_copy.hand._cards = player.hand._cards.copy()

    maybe_mocked_players = (
        [mock_player(p) if p is not current_player else p for p in game_round.players]
        if with_mock
        else game_round.players
    )
    allow_mutation = {maybe_mocked_players[p.id] for p in allow_mutation}
    with unittest.mock.patch.object(game_round, "players", new=maybe_mocked_players):
        try:
            yield game_round
        finally:
            assert game_round.state is state
            assert game_round.current_player is current_player
            for before, after in zip(round_copy.players, game_round.players):
                if after in allow_mutation:
                    continue
                assert after.alive == before.alive
                assert list(after.hand) == list(before.hand)
                assert after.immune == before.immune
                assert after.discarded_cards == before.discarded_cards
                if with_mock and after is not current_player:
                    after: Mock
                    after.eliminate.assert_not_called()
                    after.play_card.assert_not_called()
                    after.give.assert_not_called()
                    after.hand.add.assert_not_called()


def mock_player(player: RoundPlayer):
    mock = Mock(spec=player, wraps=player)
    mock.hand = mock_hand(player.hand)
    mock.round = MagicMock(spec=player.round, wraps=player.round)
    if player is player.round.current_player:
        mock.round.state.current_player = mock
        mock.round.current_player = mock
    type(mock).alive = PropertyMock(side_effect=lambda: player.alive)
    # Have to make immune a property that tracks the value since bool is immutable
    type(mock).immune = PropertyMock(side_effect=lambda: player.immune)
    mock.discarded_cards = player.discarded_cards
    mock.play_card.side_effect = functools.partial(RoundPlayer.play_card, mock)
    mock._discard_actions.side_effect = functools.partial(
        RoundPlayer._discard_actions, mock
    )
    return mock


def mock_hand(hand: RoundPlayer.Hand):
    mock = Mock(spec=hand, wraps=hand)
    type(mock).card = PropertyMock(
        side_effect=functools.partial(type(hand).card.fget, mock)
    )
    mock.__iter__ = lambda self: iter(hand)
    mock.__len__ = lambda self: len(hand)
    mock.__contains__ = lambda self, value: value in hand
    mock._cards = hand._cards
    return mock


def force_next_turn(game_round: Round):
    turn: Turn = game_round.state
    assert turn.type == RoundState.Type.TURN
    turn._set_stage(Turn.Stage.COMPLETED)
    return game_round.advance_turn()


def restart_turn(game_round: Round):
    turn: Turn = game_round.state
    assert turn.type == RoundState.Type.TURN
    turn._set_stage(Turn.Stage.START)


def force_end_round(game_round: Round):
    game_round.state = EndState(frozenset(game_round.players))


def send_gracious(gen: Generator, value: Any):
    try:
        return gen.send(value)
    except StopIteration as e:
        return e.value


def make_round_mock():
    round_ = Round(2)
    round_.start()
    player = round_.current_player
    round_mock = MagicMock(wraps=round_)
    round_mock.current_player = round_mock.state.current_player = player
    type(round_mock).living_players = PropertyMock(
        side_effect=lambda: round_.living_players
    )
    round_mock.players = round_.players
    for p in round_mock.players:
        p.round = round_mock
    return round_mock


def card_from_card_type(card_type: CardType):
    return card_type.card_class()


def play_with_choices(
    player: RoundPlayer, card_type: CardType, *choices, advance_turn=True
):
    move_ = player.play_type(card_type)
    step = None
    for choice in choices:
        step = move_.send(step)
        step.choice = choice
    result = send_gracious(move_, step)
    if advance_turn:
        player.round.advance_turn()
    return result


def start_round_from_player_cards(
    *player_cards: Sequence[cards.Card], first_player: int, set_aside=None
):
    """
    Create a round that will deal to each player the specified sequence of cards.

    The deck is built in a way so that player i starts with player_cards[i][0] and
    is dealt the cards in player_cards[i][1:] in order at each successive turn.
    This assumes that no player is eliminated before the last card in player_cards[i]
    is dealt to them.

    :param player_cards: A varargs sequence of card sequences that each player
                         will receive during the round. The first list corresponds
                         to player 0, then player 1, and so on.
    :param first_player: ID (index) of the first player to play in the round. This is
                         (also) needed to build the deck so that player_cards[i] always
                         corresponds to player i (*not* the i-th player to play).
    :param set_aside: Which card to set aside in the deck. Default is a new instance of
                      :class:`cards.Princess`.
    :return: A round with the number of players and deck deduced from ``player_cards``.
    """
    player_cards = player_cards[first_player:] + player_cards[:first_player]
    stack = list(mitt.roundrobin(*player_cards))[::-1]
    deck = Deck(stack, set_aside=set_aside or cards.Princess())
    round = Round(len(player_cards), deck=deck)
    round.start(first_player=round.players[first_player])
    return round
