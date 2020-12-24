import abc
import enum
from dataclasses import dataclass
from typing import Any, ClassVar, List

from loveletter.game import Game
from loveletter_multiplayer.utils import EnumPostInitMixin


@dataclass(frozen=True)
class Message(EnumPostInitMixin, metaclass=abc.ABCMeta):
    class Type(enum.Enum):
        OK = enum.auto()
        LOGON = enum.auto()
        ERROR = enum.auto()
        READY = enum.auto()
        READ_REQUEST = enum.auto()
        DATA = enum.auto()
        GAME_CREATED = enum.auto()

    type: ClassVar[Type]


@dataclass(frozen=True)
class Logon(Message):
    """A client logging on to the server."""

    type = Message.Type.LOGON

    username: str


class OkMessage(Message):
    """An "acknowledgement" response message."""

    type = Message.Type.OK


@dataclass(frozen=True)
class Error(Message):
    type = Message.Type.ERROR

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


@dataclass(frozen=True)
class ReadyToPlay(Message):
    """Sent by the party host to indicate that the party is ready to play."""

    type = Message.Type.READY


@dataclass(frozen=True)
class ReadRequest(Message):
    """
    Attribute access on a remote game object.

    The request string must be of the form ``game.<attr>.<subattr>.[...]``, i.e. a
    nested attribute access expression with the top-level name being ``game``.
    """

    type = Message.Type.READ_REQUEST

    request: str


@dataclass(frozen=True)
class DataMessage(Message):
    """A message containing some data (e.g., as a response to a ReadRequest)."""

    type = Message.Type.DATA

    data: Any


@dataclass(frozen=True)
class GameCreated(Message):
    """A message sent from the server to indicate that a game has been created."""

    type = Message.Type.GAME_CREATED

    players: List[Game.Player]
