import enum
from dataclasses import dataclass


@dataclass(frozen=True)
class UserInfo:
    username: str


class PlayMode(enum.Enum):
    HOST = "host"  #: host a game
    JOIN = "join"  #: join an existing game


class ServerLocation(enum.Enum):
    LOCAL = "local"  #: the server is started on the host player's machine
    EXTERNAL = "external"  #: use an existing external server on the internet


class HostVisibility(enum.Enum):
    LOCAL = "local"  #: local network only
    PUBLIC = "public"  #: visible from the internet


class MoveChoice(enum.Enum):
    LEFT = 0
    RIGHT = 1
