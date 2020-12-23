import abc
import enum
from dataclasses import dataclass
from typing import ClassVar

from loveletter_multiplayer.utils import EnumPostInitMixin


@dataclass(frozen=True)
class Message(EnumPostInitMixin, metaclass=abc.ABCMeta):
    class Type(enum.Enum):
        OK = enum.auto()
        LOGON = enum.auto()
        ERROR = enum.auto()

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

    error_code: Code
    message: str
