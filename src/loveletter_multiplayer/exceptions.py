import valid8


class LoveletterMultiplayerError(RuntimeError):
    pass


class LogonError(LoveletterMultiplayerError):
    pass


class PartyPermissionError(LoveletterMultiplayerError, valid8.InputValidationError):
    help_msg = "Only the party host can do this"


class InternalValidationError(LoveletterMultiplayerError, valid8.InputValidationError):
    pass


class ProtocolError(LoveletterMultiplayerError):
    """Raised when one of the two sides didn't follow the protocol."""

    pass


class UnexpectedMessageError(ProtocolError):
    pass


class ConnectionClosedError(ProtocolError):
    pass


class RestartSession(BaseException):
    """
    Used to indicate that a client session should be restarted.

    Not a "normal" exception, hence this inherits from BaseException and not Exception
    (similarly to StopIteration, asyncio.CancelledError, etc.).
    """

    pass
