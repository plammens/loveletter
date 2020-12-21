"""The abstract base class for parts of the game such as Game and Round."""

import abc
import enum
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Dict, FrozenSet, List, Sequence, TypeVar

import more_itertools
import valid8
from valid8.validation_lib import length_between

from loveletter.gameevent import GameEventGenerator, GameResultEvent


class GameNode(metaclass=abc.ABCMeta):
    """
    Abstract base class for a game node of Love Letter.

    A game node is any of the "playable" components of the Love Letter "game
    universe". For example, both a round (:class:`loveletter.round.Round`) and a full
    game (:class:`loveletter.game.Game`) are a game node. They are called game
    *nodes* because they can be thought to be in a tree structure: each game node is
    made up of several children nodes; for instance, a game consists of several rounds.

    We can define a concept of game node "order": a Round, which is the most atomic
    and indivisible game node type, is a zeroth-order game node; a Game,
    which consists of several rounds, is a first-order game node; a second-order game
    node would be one that involves several full games; and so on. This corresponds
    to the height of the node in the aforementioned tree.

    The common attributes that make up the state of a game node are:
     - ``players``: a list of players. The type of the player objects will be specific
                    to the game node type.
     - ``state``: the current game state of the game node.
    """

    MAX_PLAYERS: ClassVar[int] = 4  # maximum number of players

    PlayerT = TypeVar("PlayerT")
    GameNodeT = TypeVar("GameNodeT", bound="GameNode")

    players: List[PlayerT]
    state: "GameNodeState"

    @valid8.validate_arg("players", length_between(2, 4), help_msg="Bad num. players")
    def __init__(self, players: Sequence[PlayerT]):
        """
        Initialise a new game node.

        :param players: The list of player objects.
        """
        self.players = list(players)
        self.state = InitState()

    @property
    def num_players(self):
        """The number of players participating in the game."""
        return len(self.players)

    @property
    def started(self):
        """Whether the game has been started yet (first round started)."""
        return self.state.type != GameNodeState.Type.INIT

    @property
    def ended(self):
        """Whether the game has ended."""
        return self.state.type == GameNodeState.Type.END

    def __repr__(self):
        attrs = self._repr_hook()
        formatted_attrs = ", ".join(f"{key}={value}" for key, value in attrs.items())
        return f"<{self.__class__.__name__} 0x{id(self):X} with {formatted_attrs}>"

    @abc.abstractmethod
    def play(self, **start_kwargs) -> GameEventGenerator:
        """
        The game event generator for this game node that runs for its duration.

        This provides a higher-level API to step-by-step methods. See
        :class:`loveletter.gameevent.GameEvent` for a description of game event
        generators.

        The return value of the generator is the final state of the game (i.e. a
        :class:`GameNodeEnd` instance).

        :param start_kwargs: Keyword arguments to be passed to :meth:`GameNode.start`.
        """
        valid8.validate(
            "started",
            self.started,
            equals=False,
            help_msg=(
                f"Can't start .play() once the {self.__class__.__name__} "
                f"has already started"
            ),
        )
        return ()
        # noinspection PyUnreachableCode
        yield

    # noinspection PyTypeChecker
    @abc.abstractmethod
    def start(self) -> "GameNodeState":
        """
        Start this game node and enter the first intermediate state.

        This base implementation just does some validation.
        """
        valid8.validate(
            "started",
            self.started,
            equals=False,
            help_msg=f"The {self.__class__.__name__} has already started",
        )

    @abc.abstractmethod
    def advance(self) -> "GameNodeState":
        """
        Advance from an intermediate state to the next (intermediate or end).

        This base implementation just does some validation.
        """
        valid8.validate(
            "started",
            self.started,
            equals=True,
            help_msg=f"The {self.__class__.__name__} hasn't started yet",
        )
        valid8.validate(
            "ended",
            self.ended,
            equals=False,
            help_msg=f"The {self.__class__.__name__} has already ended",
        )
        self.state: IntermediateState
        intermediate_name = self.state.name
        valid8.validate(
            intermediate_name,
            self.state,
            custom=lambda s: s.can_advance,
            help_msg=f"Can't advance {intermediate_name} before previous one has ended",
        )

    @abc.abstractmethod
    def _reached_end(self) -> bool:
        """Check the end condition of this game node."""
        pass

    @abc.abstractmethod
    def _finalize(self) -> "EndState":
        """End the game node and declare the winner(s)."""
        pass

    def _check_post_start(self):
        """Validate the state of the game node before exiting .start()"""
        if self._reached_end():
            raise ValueError("End condition true immediately upon starting")

    def _play_helper(
        self,
        iteration_generator: Callable[[GameNodeT], GameEventGenerator],
        **start_kwargs,
    ) -> GameEventGenerator:
        """
        Implementation help for the :meth:`GameNode.play` generator.

        :param iteration_generator: Generator function for a single "iteration" of the
                                    game node, i.e. everything that happens in between
                                    calls to :meth:`GameNode.advance`.
        :param start_kwargs: Keyword arguments to pass to :meth:`GameNode.start`.
        :return: The implementation of the :meth:`GameNode.play` game event generator.
        """
        # the `yield from (yield from ...)` is because the return value of the
        # iteration generator is a tuple of game results, which we also want to
        # yield from

        # noinspection PyArgumentList
        state = self.start(**start_kwargs)
        while state.type != GameNodeState.Type.END:
            yield state
            yield from (yield from iteration_generator(self))
            state = self.advance()
        return (state,)

    def _repr_hook(self) -> Dict[str, Any]:
        """Return an ordered mapping of name to value pairs to use in __repr__."""
        return {"players": self.players, "state": self.state}


@dataclass(frozen=True, eq=False)
class GameNodeState(GameResultEvent, metaclass=abc.ABCMeta):
    """
    Objects of this class represent the state of a game node.

    A GameNodeState object can be of one of several types, as specified in
    :class:`GameNodeState.Type`. The relationship between game state types and
    subclasses of "GameNodeState" might not necessarily be one-to-one (but it will
    always be one-to-*, i.e. every concrete subclass is of exactly one type).

    When seen as a :class:`GameResultEvent`, a "GameNodeState" instance represents
    the event corresponding to the game node entering the state described by said
    instance.

    The common attributes/properties of a GameNodeState are:
     - ``type``: the type of game state as described above
    """

    class Type(enum.Enum):
        INIT = enum.auto()  # not started yet, just initialised
        INTERMEDIATE = enum.auto()  # one of the in-progress phases of the game node
        END = enum.auto()  # game has ended

    type: ClassVar["GameNodeState.Type"]


@dataclass(frozen=True)
class InitState(GameNodeState):
    """The initial state of a game node."""

    type = GameNodeState.Type.INIT


@dataclass(frozen=True, eq=False)
class IntermediateState(GameNodeState, metaclass=abc.ABCMeta):
    """The common interface for subclasses with type=GameNodeState.Type.INTERMEDIATE."""

    type = GameNodeState.Type.INTERMEDIATE
    name: ClassVar[str]  # informal name of the intermediate state

    @property
    @abc.abstractmethod
    def can_advance(self) -> bool:
        """Whether the game node can advance to the next state."""
        pass


@dataclass(frozen=True)
class EndState(GameNodeState, metaclass=abc.ABCMeta):
    """
    Represents the final state of a game node after it has ended.

    Usually there will be only one winner (which can be accessed through the ``winner``
    property), but sometimes more. In this case, accessing ``winner`` will raise an
    error. Thus one should always check the ``winners`` attribute first.
    """

    type = GameNodeState.Type.END
    winners: FrozenSet[GameNode.PlayerT]

    @property
    def winner(self) -> GameNode.PlayerT:
        with valid8.validation(
            "winners", self.winners, help_msg="There is more than one winner"
        ):
            return more_itertools.one(self.winners, too_short=AssertionError)
