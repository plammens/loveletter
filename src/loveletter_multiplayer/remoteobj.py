"""
Defines classes to view and interact with shadow copies of remote game objects.

A shadow copy is a local copy of a remote object that is meant to be kept in sync with
the remote object.
"""
from typing import TYPE_CHECKING

import loveletter_multiplayer.networkcomms.message as msg
from loveletter.game import Game

if TYPE_CHECKING:
    pass


class RemoteGameShadowCopy(Game):
    @classmethod
    def from_server_message(cls, message: msg.GameCreated) -> "RemoteGameShadowCopy":
        """Wait for the server to start the remote game and initialise a copy."""
        return RemoteGameShadowCopy([p.username for p in message.players])
