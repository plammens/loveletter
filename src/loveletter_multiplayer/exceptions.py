import typing as tp
from dataclasses import dataclass

import valid8


if tp.TYPE_CHECKING:
    from loveletter_multiplayer.networkcomms import Message


class LoveletterMultiplayerError(RuntimeError):
    pass


class LogonError(LoveletterMultiplayerError):
    pass


class PartyPermissionError(LoveletterMultiplayerError, valid8.InputValidationError):
    help_msg = "Only the party host can do this"


class InternalValidationError(LoveletterMultiplayerError, valid8.InputValidationError):
    pass


@dataclass(frozen=True)
class RemoteException(LoveletterMultiplayerError):
    exc_type: tp.Type[Exception]
    exc_message: str

    def __post_init__(self):
        super().__init__(self.exc_type, self.exc_message)


@dataclass(frozen=True)
class RemoteValidationError(RemoteException):
    help_message: str


class ProtocolError(LoveletterMultiplayerError):
    """Raised when one of the two sides didn't follow the protocol."""

    pass


@dataclass(frozen=True)
class UnexpectedMessageError(ProtocolError):
    expected: tp.Type["Message"]
    actual: "Message"

    def __str__(self):
        return f"Expected {self.expected.__name__}, got {self.actual}"


class ConnectionClosedError(ProtocolError):
    pass


class RestartSession(BaseException):
    """
    Used to indicate that a client session should be restarted.

    Not a "normal" exception, hence this inherits from BaseException and not Exception
    (similarly to StopIteration, asyncio.CancelledError, etc.).
    """

    pass
