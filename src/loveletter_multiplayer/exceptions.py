import valid8


class LoveletterMultiplayerError(RuntimeError):
    pass


class LogonError(LoveletterMultiplayerError):
    pass


class PartyPermissionError(LoveletterMultiplayerError, valid8.InputValidationError):
    help_msg = "Only the party host can do this"


class InternalValidationError(LoveletterMultiplayerError, valid8.InputValidationError):
    pass
