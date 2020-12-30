import enum
from dataclasses import dataclass


@dataclass
class Session:
    """CLI session manager."""

    user: "UserInfo"

    def host_game(self, host: str, port: int):
        pass

    def join_game(self, host: str, port: int):
        pass


@dataclass(frozen=True)
class UserInfo:
    username: str


class PlayMode(enum.Enum):
    HOST = enum.auto()  #: host a game
    JOIN = enum.auto()  #: join an existing game


class HostVisibility(enum.Enum):
    LOCAL = enum.auto()  #: local network only
    PUBLIC = enum.auto()  #: visible from the internet
