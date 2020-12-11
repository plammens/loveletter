import collections
import contextlib
import copy
import functools
import inspect
import math
import random
import unittest.mock
from typing import Any, Collection, Counter, Generator, Tuple, Type, TypeVar, Union
from unittest.mock import MagicMock, Mock, PropertyMock

import pytest
from multimethod import multimethod

import loveletter.cards as cards
import loveletter.move as move
from loveletter.cardpile import STANDARD_DECK_COUNTS
from loveletter.cards import Card, CardType
from loveletter.player import Player
from loveletter.round import Round, RoundState, Turn
from test_loveletter import test_cards_cases as card_cases


_T = TypeVar("_T")


def collect_subclasses(base_class: Type[_T], module) -> Collection[Type[_T]]:
    def is_strict_subclass(obj):
        return (
            inspect.isclass(obj)
            and issubclass(obj, base_class)
            and obj is not base_class
        )

    return list(filter(is_strict_subclass, vars(module).values()))


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
    while not game_round.ended:
        player = game_round.current_player
        card = random.choice(list(player.hand))
        autofill_move(player.play_card(card))
        game_round.advance_turn()


def autofill_move(
    move_: cards.MoveStepGenerator, start_step=None, num_steps: int = None, close=None
) -> Union[move.MoveStep, Tuple[move.MoveResult, ...]]:
    """
    Automatically play a move by making (arbitrary) choices for each of the steps.

    Useful if the test doesn't care about the specifics of the move, just wants to play
    it out.

    :param move_: Move step generator as returned by Player.play().
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
def autofill_step(step: move.MoveStep):
    """Fulfill a move step by making a(n arbitrary) choice"""
    raise TypeError(f"autofill_step not implemented for {type(step)}")


@autofill_step.register
def autofill_step(step: Union[type(None), Mock]):
    # special case for None and mock steps
    return step


@autofill_step.register
def autofill_step(step: move.PlayerChoice):
    step.choice = random.choice(step.game_round.living_players)
    return step


@autofill_step.register
def autofill_step(step: move.OpponentChoice):
    game_round = step.game_round
    player = step.player
    players = set(game_round.living_players)
    opponents = players - {player} - {p for p in players if p.immune}
    step.choice = random.choice(list(opponents)) if opponents else None
    return step


@autofill_step.register
def autofill_step(step: move.CardGuess):
    step.choice = cards.Guard()
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


def make_mock_move(player):
    card_mock = card_cases.CardMockCases().case_generic()
    play_card(player, card_mock, autofill=True)


def play_card(player: Player, card: cards.Card, autofill=None, skip_if_disallowed=True):
    from test_loveletter.test_cards_cases import DISCARD_TYPES

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
def play_card_with_cleanup(player: Player, card: cards.Card):
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


def give_card(player: Player, card: Card, replace=False):
    if replace:
        player.hand._cards.clear()
    elif len(player.hand) == 2:
        player.hand._cards.pop()
    player.give(card)


@contextlib.contextmanager
def assert_state_is_preserved(
    game_round: Round, allow_mutation: Collection[Player] = (), with_mock=True
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
                assert after.cards_played == before.cards_played
                if with_mock and after is not current_player:
                    after: Mock
                    after.eliminate.assert_not_called()
                    after.play_card.assert_not_called()
                    after.give.assert_not_called()
                    after.hand.add.assert_not_called()


def mock_player(player: Player):
    mock = Mock(spec=player, wraps=player)
    mock.hand = mock_hand(player.hand)
    mock.round = MagicMock(spec=player.round, wraps=player.round)
    if player is player.round.current_player:
        mock.round.state.current_player = mock
        mock.round.current_player = mock
    type(mock).alive = PropertyMock(side_effect=lambda: player.alive)
    # Have to make immune a property that tracks the value since bool is immutable
    type(mock).immune = PropertyMock(side_effect=lambda: player.immune)
    mock.cards_played = player.cards_played
    mock.play_card.side_effect = functools.partial(Player.play_card, mock)
    mock._discard_actions.side_effect = functools.partial(Player._discard_actions, mock)
    return mock


def mock_hand(hand: Player.Hand):
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
    assert game_round.state.type == RoundState.Type.TURN
    game_round.state.stage = Turn.Stage.COMPLETED
    return game_round.advance_turn()


def restart_turn(game_round: Round):
    assert game_round.state.type == RoundState.Type.TURN
    game_round.state.stage = Turn.Stage.START
    return game_round.state


def send_gracious(gen: Generator, value: Any):
    try:
        return gen.send(value)
    except StopIteration as e:
        return e.value
