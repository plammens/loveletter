import abc
import enum
from dataclasses import dataclass, field
from typing import Any, ClassVar, List, Type

import loveletter.cardpile
import loveletter.game
import loveletter.gameevent
import loveletter.gamenode
from loveletter_multiplayer.utils import EnumPostInitMixin


@dataclass(frozen=True)
class Message(EnumPostInitMixin, metaclass=abc.ABCMeta):
    _types: ClassVar[List[Type["Message"]]] = []

    @staticmethod
    def register(cls):
        """Class decorator to register a concrete type of Message."""
        Message._types.append(cls)
        return cls

    @classmethod
    def to_type_id(cls) -> int:
        """Return a numeric ID for this type of Message."""
        return Message._types.index(cls)

    @staticmethod
    def from_type_id(type_id: int) -> Type["Message"]:
        """Return the Message subtype for a given numeric ID."""
        return Message._types[type_id]


@Message.register
@dataclass(frozen=True)
class Logon(Message):
    """A client logging on to the server."""

    username: str


@Message.register
@dataclass(frozen=True)
class OkMessage(Message):
    """An "acknowledgement" response message."""


@Message.register
@dataclass(frozen=True)
class ErrorMessage(Message):
    class Code(enum.Enum):
        """Enum for error codes."""

        CONNECTION_REFUSED = enum.auto()
        LOGON_ERROR = enum.auto()
        PERMISSION_DENIED = enum.auto()
        ATTRIBUTE_ERROR = enum.auto()
        SERIALIZE_ERROR = enum.auto()
        EXCEPTION = enum.auto()
        RESTART_SESSION = enum.auto()
        SESSION_ABORTED = enum.auto()

    error_code: Code
    message: str


@Message.register
@dataclass(frozen=True)
class ExceptionMessage(ErrorMessage):
    error_code: ErrorMessage.Code = field(
        init=False, default=ErrorMessage.Code.EXCEPTION, repr=False
    )

    exc_type: Type[Exception]
    exc_message: str


@Message.register
@dataclass(frozen=True)
class ReadyToPlay(Message):
    """Sent by the party host to indicate that the party is ready to play."""


@Message.register
@dataclass(frozen=True)
class Shutdown(Message):
    """Sent by the party host at the end of a game to allow the server to shut down."""


@Message.register
@dataclass(frozen=True)
class ReadRequest(Message):
    """
    Attribute access on a remote game object.

    The request string must be of the form ``game.<attr1>.<attr2>.[...]``, i.e. a
    nested attribute access expression with the top-level name being ``game``.
    """

    request: str


@Message.register
@dataclass(frozen=True)
class DataMessage(Message):
    """A message containing some data (e.g., as a response to a ReadRequest)."""

    data: Any


@Message.register
@dataclass(frozen=True)
class GameCreated(Message):
    """A message sent from the server to indicate that a game has been created."""

    players: List[loveletter.game.Game.Player]
    player_id: int  #: the player id assigned to the client to which this is being sent


@dataclass(frozen=True)
class GameMessage(Message, metaclass=abc.ABCMeta):
    """Any of the messages passed as part of the game logic."""


@Message.register
@dataclass(frozen=True)
class GameNodeStateMessage(GameMessage):
    """Sent by the server to synchronise the game state."""

    state: loveletter.gamenode.GameNodeState


@Message.register
@dataclass(frozen=True)
class RoundInitMessage(GameNodeStateMessage):
    """Includes deck info so clients can synchronize their local games."""

    state: loveletter.game.PlayingRound
    deck: loveletter.cardpile.Deck


@Message.register
@dataclass(frozen=True)
class GameInputRequestMessage(GameMessage):
    """Game input request wrapper message."""

    request: loveletter.gameevent.GameInputRequest
    id: int  #: game-wide unique identifier for the request

    def __post_init__(self):
        super().__post_init__()
        if self.request.fulfilled:
            raise ValueError("Request is already fulfilled")


@Message.register
@dataclass(frozen=True)
class FulfilledChoiceMessage(GameMessage):
    """Sent from a client to indicate the choice for a fulfilled game input step."""

    choice_class: str  #: fully qualified name of the ChoiceEvent subclass
    choice: loveletter.gameevent.Serializable  #: serializable value of choice (ChoiceEvent.to_serializable)

    def __post_init__(self):
        super().__post_init__()
        if self.choice is None:
            raise ValueError("Choice is not fulfilled")


@Message.register
@dataclass(frozen=True)
class GameEndMessage(GameMessage):
    """Sent from the server to indicate the game has ended."""

    game_end: loveletter.game.GameEnd
