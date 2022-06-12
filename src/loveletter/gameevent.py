import abc
from dataclasses import dataclass
from typing import Any, Collection, Generator, Optional, Tuple, Union

import valid8


class GameEvent(metaclass=abc.ABCMeta):
    """
    Any of the events involved in a game.

    These are the type of objects handled by game event generators (see the
    GameEventGenerator alias below). A game event generator is a generator that yields
    a GameEvent object at each step of the game process it is responsible for. These
    can be either :class:`GameInputRequest`o or :class:`GameResultEvent`o. A game input
    event indicates a request of input from a player, while a game result event
    summarises the result of a game action.

    When a game event generator yields a GameInputRequest instance, it expects the same
    instance to be appropriately "filled" and sent back to the generator with the next
    call to .send(). If a GameResultEvent is yielded, any object sent back to the
    generator is ignored.
    """

    pass


class GameInputRequest(GameEvent, metaclass=abc.ABCMeta):
    """
    A request of input from an external entity (e.g., a player).

    Objects of this class are mutable as they're intended to be "filled in" by the
    external entity with appropriate information and sent back to the event generator
    that yielded them.
    """

    @property
    @abc.abstractmethod
    def fulfilled(self) -> bool:
        return False

    def __eq__(self, other):
        """Default state-based equality."""
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.__dict__ == other.__dict__

    def __repr__(self):
        return (
            f"<{'fulfilled' if self.fulfilled else 'unfulfilled'}"
            f" {self.__class__.__name__}>"
        )

    def __iter__(
        self,
    ) -> Generator["GameInputRequest", "GameInputRequest", "GameInputRequest"]:
        """A more aesthetic alternative to .yield_helper()."""
        return self.yield_helper()

    def yield_helper(
        self,
    ) -> Generator["GameInputRequest", "GameInputRequest", "GameInputRequest"]:
        """
        A helper generator that yields this input request with validation.

        It yields a single object ``self``. When execution resumes, it checks that
        ``self`` was sent back and was fulfilled. Finally, if validation completes
        successfully, the return value of the generator is, again, ``self``.
        """
        completed = yield self
        valid8.validate(
            "completed_step",
            completed,
            custom=lambda o: o is self,
            help_msg=(
                "Did not receive the same GameInputRequest that was yielded: "
                "expected {expected}, got {actual}"
            ),
            expected=self,
            actual=completed,
        )
        valid8.validate(
            "completed_step",
            completed,
            custom=lambda r: r.fulfilled,
            help_msg="Received an unfulfilled GameInputRequest step",
        )
        return completed


@dataclass(frozen=True)
class GameResultEvent(GameEvent, metaclass=abc.ABCMeta):
    """
    An atomic result of a player's action or any other game process.

    These objects are (intended to be) immutable, since they're just encapsulating a
    unit of information about something that happened in the game.
    """

    pass


# see GameEvent for docs
GameEventGenerator = Generator[GameEvent, GameInputRequest, Tuple[GameResultEvent, ...]]


Serializable = Union[None, int, float, str, tuple, list, dict]


class ChoiceEvent(GameInputRequest, metaclass=abc.ABCMeta):
    """A game input event consisting of a simple choice."""

    def __init__(self):
        self._choice = None

    @property
    @abc.abstractmethod
    def options(self) -> Collection:
        """The possible options for this choice."""
        pass

    @property
    def choice(self) -> Optional[Any]:
        return self._choice

    @choice.setter
    def choice(self, value):
        self._validate_choice(value)
        self._choice = value

    @property
    def fulfilled(self) -> bool:
        return self._choice is not None

    def __repr__(self):
        return (
            super().__repr__()
            if not self.fulfilled
            else f"<fulfilled {self.__class__.__name__} with choice {self.choice}>"
        )

    @abc.abstractmethod
    def to_serializable(self) -> Serializable:
        """Return a serializable value representing this choice."""
        valid8.validate(
            "fulfilled",
            self.fulfilled,
            equals=True,
            help_msg="Choice hasn't been set yet",
        )
        return self.choice

    @abc.abstractmethod
    def from_serializable(self, value: Serializable) -> Any:
        """
        The inverse of :meth:`ChoiceEvent.to_serializable`.

        Returns a choice object reconstructed from the serialized value.
        """

    def set_from_serializable(self, value: Serializable) -> None:
        """Set the choice from the value returned by :meth:`to_serializable`."""
        self.choice = self.from_serializable(value)

    def _validate_choice(self, value):
        """Validate the current choice"""
        valid8.validate(
            "choice",
            value,
            is_in=self.options,
            help_msg="Not a valid option",
        )
