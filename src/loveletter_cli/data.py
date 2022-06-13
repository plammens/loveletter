import enum
from dataclasses import dataclass


@dataclass(frozen=True)
class UserInfo:
    username: str


class PlayMode(enum.Enum):
    HOST = "host"  #: host a game
    JOIN = "join"  #: join an existing game


class HostVisibility(enum.Enum):
    LOCAL = "local"  #: local network only
    PUBLIC = "public"  #: visible from the internet


class MoveChoice(enum.Enum):
    LEFT = 0
    RIGHT = 1
