"""Stable, user-safe errors for the command line and library."""


class EvidenceLoopError(Exception):
    """Base class with a machine-readable code and safe message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class InputError(EvidenceLoopError):
    pass


class PathSafetyError(EvidenceLoopError):
    pass


class OutputError(EvidenceLoopError):
    pass
