import enum
from dataclasses import dataclass


@dataclass(frozen=True)
class UserInfo:
    username: str


class PlayMode(enum.Enum):
    HOST = enum.auto()  #: host a game
    JOIN = enum.auto()  #: join an existing game


class HostVisibility(enum.Enum):
    LOCAL = enum.auto()  #: local network only
    PUBLIC = enum.auto()  #: visible from the internet


class MoveChoice(enum.Enum):
    LEFT = 0
    RIGHT = 1
