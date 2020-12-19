import abc
import enum
from collections import Counter
from dataclasses import dataclass
from typing import Optional, Sequence, Counter as CounterType

from loveletter.cards import CardType
from loveletter.gameevent import GameEventGenerator
from loveletter.gamenode import EndState, GameNode, GameNodeState, IntermediateState
from loveletter.round import FirstPlayerChoice, Round
from loveletter.utils import extend_enum


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
        id: int
        username: str

        def __str__(self):
            return f"{self.username} (player-{self.id})"

    points: CounterType[Player]  # tokens of affection

    def __init__(self, players: Sequence[str]):
        """
        Initialise a new game.

        :param players: The usernames of each player in the round. Must be of length
                        between 2 and 4.
        """
        players = [Game.Player(i, uname) for i, uname in enumerate(players)]
        super().__init__(players)
        self.points = Counter()

    @property
    def points_threshold(self):
        """The number of points that must be reached by a player to win."""
        return {2: 7, 3: 5, 4: 4}[self.num_players]

    def play(self, **start_kwargs) -> GameEventGenerator:
        def iteration(self: Game) -> GameEventGenerator:
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

            return (yield from game_round.play(first_player=first_player))

        yield from super().play()
        return (yield from self._play_helper(iteration, **start_kwargs))

    def start(self):
        super().start()
        first_round = Round(self.num_players)
        self.state = state = PlayingRound(
            round=first_round, round_no=1, first_player=None
        )
        return state

    def advance(self) -> "GameNodeState":
        if (state := super().advance()) is not None:
            return state

        self.state: PlayingRound
        old_round = self.state.round
        self._collect_points(old_round)

        new_round = Round(self.num_players)
        new_round_no = self.state.round_no + 1
        # the game should always be finished by this number of rounds
        assert new_round_no <= self.num_players * (self.points_threshold - 1)
        try:
            # noinspection PyUnresolvedReferences
            first_player = old_round.state.winner
        except ValueError:
            # more than one winner
            first_player = None
        self.state = state = PlayingRound(
            round=new_round, round_no=new_round_no, first_player=first_player
        )
        return state

    advance_round = advance

    def _reached_end(self) -> bool:
        """Whether this game has reached to an end."""
        return any(p >= self.points_threshold for p in self.points.values())

    def _finalize(self) -> EndState:
        """End the game and declare the winner(s)."""
        winners = frozenset(
            player
            for player, points in self.points.items()
            if points >= self.points_threshold
        )
        self.state = end = EndState(winners=winners)
        return end

    def _collect_points(self, game_round: Round):
        """Collect tokens of affection from a round that has ended."""
        # noinspection PyUnresolvedReferences
        points = Counter(game_round.state.winners)
        for card_type in CardType:
            points.update(card_type.card_class.collect_extra_points(game_round))
        self.points.update({self.players[p.id]: pts for p, pts in points.items()})


@dataclass(frozen=True, eq=False)
class GameState(GameNodeState, metaclass=abc.ABCMeta):
    """Intermediate ABC for full-game states"""

    @extend_enum(GameNodeState.Type)
    class Type(enum.Enum):
        # currently playing some round; alias for INTERMEDIATE
        ROUND = GameNodeState.Type.INTERMEDIATE.value


@dataclass(frozen=True, eq=False)
class PlayingRound(GameState, IntermediateState):
    """
    Represents the state of the game while playing one of its rounds.

    The game can only start a new round when the previous one has been completed.
    """

    type = GameState.Type.ROUND
    name = "round"

    round: Round
    round_no: int
    first_player: Optional[Game.Player]  # who will start the round, if known

    @IntermediateState.can_advance.getter
    def can_advance(self) -> bool:
        return self.round.ended
