import collections
import contextlib
import copy
import functools
import inspect
import random
import unittest.mock
from typing import Any, Collection, Counter, Generator, Type, TypeVar
from unittest.mock import Mock, PropertyMock

import pytest

from loveletter import cards as cards
from loveletter.cardpile import STANDARD_DECK_COUNTS
from loveletter.cards import Card
from loveletter.move import MoveStep
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


def random_card_counts() -> Counter[Type[Card]]:
    counts = collections.Counter(
        {
            cls: random.randint(0, max_count)
            for cls, max_count in STANDARD_DECK_COUNTS.items()
        }
    )
    # Remove classes with 0 count:
    for cls, count in tuple(counts.items()):
        if count == 0:
            del counts[cls]
    return counts


def autofill_moves(steps: Generator[MoveStep, MoveStep, None]):
    # for now just consume generator
    step = None
    # fmt: off
    try:
        while True: step = steps.send(step)
    except StopIteration: pass
    # fmt: on


def send_final(gen: Generator, value: Any) -> Any:
    try:
        with pytest.raises(StopIteration):
            return gen.send(value)
    except StopIteration as e:
        return e.value


def make_mock_move(player):
    card_mock = card_cases.CardMockCases().case_generic()
    play_card(player, card_mock, autofill=True)


def play_card(player: Player, card: cards.Card, autofill=None):
    from test_loveletter.test_cards_cases import DISCARD_TYPES

    if autofill is None:
        autofill = cards.CardType(type(card)) in DISCARD_TYPES

    player.give(card)
    move = player.play_card(card)
    if autofill:
        autofill_moves(move)
        return None
    else:
        return move


@contextlib.contextmanager
def assert_state_is_preserved(game_round: Round, with_mock=True):
    state = game_round.state
    current_player = game_round.current_player
    round_copy = copy.deepcopy(game_round)
    # player cards should be a shallow copy:
    for player, player_copy in zip(game_round.players, round_copy.players):
        player_copy.hand._cards = player.hand._cards.copy()

    maybe_mocked_players = (
        list(map(mock_player, game_round.players)) if with_mock else game_round.players
    )
    with unittest.mock.patch.object(game_round, "players", new=maybe_mocked_players):
        try:
            yield
        finally:
            assert game_round.state is state
            assert game_round.current_player is current_player
            for before, after in zip(round_copy.players, game_round.players):
                assert after.alive == before.alive
                assert list(after.hand) == list(before.hand)
                assert after.immune == before.immune
                assert after.cards_played == before.cards_played
                if with_mock:
                    after: Mock
                    after.eliminate.assert_not_called()
                    after.play_card.assert_not_called()
                    after.give.assert_not_called()
                    after.hand.add.assert_not_called()


def mock_player(player: Player):
    mock = Mock(spec=player, wraps=player)
    mock.hand = mock_hand(player.hand)
    type(mock).alive = PropertyMock(side_effect=lambda: player.alive)
    # Have to make immune a property that tracks the value since bool is immutable
    type(mock).immune = PropertyMock(side_effect=lambda: player.immune)
    mock.cards_played = player.cards_played
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
    return game_round.next_turn()
