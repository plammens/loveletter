import abc
import enum
from dataclasses import dataclass
from typing import ClassVar

from loveletter_multiplayer.utils import EnumPostInitMixin


@dataclass(frozen=True)
class Message(EnumPostInitMixin, metaclass=abc.ABCMeta):
    class Type(enum.Enum):
        PING = enum.auto()
        ERROR = enum.auto()

    type: ClassVar[Type]


@dataclass(frozen=True)
class Ping(Message):
    type = Message.Type.PING


@dataclass(frozen=True)
class ErrorMessage(Message):
    type = Message.Type.ERROR

    class Code(enum.Enum):
        """Enum for error codes."""

        CONNECTION_REFUSED = enum.auto()

    error_code: Code
    message: str
