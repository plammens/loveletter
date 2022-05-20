import abc
import enum
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Counter as CounterType, Dict, Optional, Sequence

import valid8
from multimethod import multimethod
from valid8.validation_lib import instance_of, on_all_

from loveletter.cards import CardType
from loveletter.gameevent import GameEventGenerator, GameResultEvent
from loveletter.gamenode import (
    EndState,
    GameNode,
    GameNodeState,
    InitState,
    IntermediateState,
)
from loveletter.round import FirstPlayerChoice, Round
from loveletter.roundplayer import RoundPlayer
from loveletter.utils import argmax, extend_enum


class Game(GameNode):
    """
    A complete game of Love Letter.

    The main attributes/properties that make up the state of a Game are:
     - ``players``: A list of ``Game.Player``s  (a physical player). At each round,
                    ``round.players[i]`` corresponds to ``game.players[i]``. The
                    ID of each player equals their index in this list.
     - ``points``: A mapping of players (from ``game.players``) to game points
                   ("tokens of affection", officially). A player must reach a certain
                   number of points (given by :attr:`Game.points_threshold`) in order
                   to win the game.
     - ``state``: The current state of the game (e.g. the current round, or the result
                  of the game if the game has ended).
    """

    @dataclass(frozen=True, eq=False)
    class Player:
        game: "Game" = field(repr=False)
        id: int
        username: str

        def __str__(self):
            return f"{self.username} (player-{self.id})"

        @property
        def round_player(self):
            current_round = self.game.current_round
            return current_round.players[self.id] if current_round is not None else None

        def __getattr__(self, item):
            if (round_ := self.game.current_round) is not None:
                return getattr(round_.players[self.id], item)
            raise AttributeError(item)

    points: CounterType[Player]  # tokens of affection

    @valid8.validate_arg("players", on_all_(instance_of(str)))
    def __init__(self, players: Sequence[str]):
        """
        Initialise a new game.

        :param players: The usernames of each player in the round. Must be of length
                        between 2 and ``GameNode.MAX_PLAYERS``.
        """
        players = [Game.Player(self, i, uname) for i, uname in enumerate(players)]
        super().__init__(players)
        self.points = Counter({p: 0 for p in self.players})

        # whether the current round's points have been collected
        self._points_updated: bool = False

    @property
    def points_threshold(self) -> int:
        """The number of points that must be reached by a player to win."""
        return {2: 6, 3: 5, 4: 4, 5: 3, 6: 3}[self.num_players]

    @property
    def current_round(self) -> Optional[Round]:
        """The current round being played, or None if not applicable."""
        return getattr(self.state, "round", None)

    @multimethod
    def get_player(self, player: "Game.Player") -> "Game.Player":
        """Utility to get the appropriate Game.Player object."""
        return player

    @get_player.register
    def get_player(self, player: int) -> "Game.Player":
        return self.players[player]

    @get_player.register
    def get_player(self, player: RoundPlayer) -> "Game.Player":
        valid8.validate(
            "player",
            player,
            is_in=self.current_round.players,
            help_msg="This RoundPlayer is not from this game",
        )
        return self.players[player.id]

    def _play_round(self) -> GameEventGenerator:
        # noinspection PyTypeChecker
        state: PlayingRound = self.state
        game_round = state.round

        # first, determine who will start the round: if available, use the winner
        # from last round, otherwise let the players choose
        first_player = (
            game_round.players[state.first_player.id]
            if state.first_player is not None
            else (yield from FirstPlayerChoice(game_round)).choice  # noqa
        )

        (round_end,) = yield from game_round.play(first_player=first_player)
        points_update = PointsUpdate(self.update_points())
        return (round_end, points_update)

    _play_iteration = _play_round

    def start(self):
        super().start()
        first_round = Round(self.num_players)
        self.state = state = PlayingRound(
            round=first_round, round_no=1, first_player=None
        )
        return state

    def advance(self) -> "GameNodeState":
        super().advance()

        self.state: PlayingRound
        old_round = self.state.round
        if not self._points_updated:
            self.update_points()
        if self._reached_end():
            return self._finalize()

        new_round = Round(self.num_players)
        new_round_no = self.state.round_no + 1
        # the game should always be finished by this number of rounds
        assert new_round_no <= self.num_players * (self.points_threshold - 1) + 1
        try:
            # noinspection PyUnresolvedReferences
            first_player = old_round.state.winner
        except ValueError:
            # more than one winner
            first_player = None

        self.state = state = PlayingRound(
            round=new_round,
            round_no=new_round_no,
            first_player=first_player,
        )
        self._points_updated = False

        return state

    advance_round = advance

    @valid8.validate_arg(
        "self",
        lambda g: not g._points_updated,  # noqa
        help_msg="Points have already been updated for this round",
    )
    @valid8.validate_arg(
        "self",
        lambda g: getattr(g.current_round, "ended", False),
        help_msg="Round hasn't ended yet",
    )
    def update_points(self) -> Counter["Player"]:
        """
        After a round has ended, update each player's tokens of affection.

        Can only be called once per round, after the round has ended.

        :return: A counter indicating the delta in points for each player.
        """
        points_update = self._collect_points(self.current_round)
        self.points.update(points_update)
        self._points_updated = True
        return points_update

    @classmethod
    def _make_init_state(cls):
        return InitGameState()

    def _reached_end(self) -> bool:
        """Whether this game has reached to an end."""
        return any(p >= self.points_threshold for p in self.points.values())

    def _finalize(self) -> "GameEnd":
        """End the game and declare the winner(s)."""
        winners = frozenset(argmax(self.players, key=self.points.__getitem__))
        self.state = end = GameEnd(winners=winners)
        return end

    def _collect_points(self, game_round: Round) -> Counter["Game.Player"]:
        """Collect tokens of affection from a round that has ended."""
        assert game_round.ended
        # noinspection PyUnresolvedReferences
        points = Counter(game_round.state.winners)
        for card_type in CardType:
            points.update(card_type.card_class.collect_extra_points(game_round))
        points_update = Counter({self.players[p.id]: pts for p, pts in points.items()})
        return points_update

    def _repr_hook(self) -> Dict[str, Any]:
        attrs = super()._repr_hook()
        attrs["players"] = [player.username for player in self.players]
        attrs["points"] = self.points
        return attrs


@dataclass(frozen=True)
class GameState(GameNodeState, metaclass=abc.ABCMeta):
    """Intermediate ABC for full-game states"""

    @extend_enum(GameNodeState.Type)
    class Type(enum.Enum):
        # currently playing some round; alias for INTERMEDIATE
        ROUND = GameNodeState.Type.INTERMEDIATE.value


@dataclass(frozen=True)
class InitGameState(GameState, InitState):
    pass


@dataclass(frozen=True)
class PlayingRound(GameState, IntermediateState):
    """
    Represents the state of the game while playing one of its rounds.

    The game can only start a new round when the previous one has been completed.
    """

    type = GameState.Type.ROUND
    name = "round"

    round: Round
    round_no: int
    first_player: Optional[Game.Player]  #: who will start the round, if known

    @IntermediateState.can_advance.getter
    def can_advance(self) -> bool:
        return self.round.ended


@dataclass(frozen=True)
class PointsUpdate(GameResultEvent):
    """Informs about a points update after a round has ended."""

    points_update: Counter[Game.Player]  # points delta per player


@dataclass(frozen=True)
class GameEnd(GameState, EndState):
    pass
