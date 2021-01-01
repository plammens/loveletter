"""
Defines classes to view and interact with shadow copies of remote game objects.

Implements the client-side logic for managing a multiplayer game. A "shadow copy" is a
local copy of a remote object that is meant to be kept in sync with the remote
object.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Sequence, TYPE_CHECKING, Type

from multimethod import multimethod

import loveletter.game
import loveletter.gameevent as gev
import loveletter.gamenode as gnd
import loveletter.move as move
import loveletter.round as rnd
import loveletter_multiplayer.networkcomms.message as msg
from loveletter.cards import CardType
from loveletter_multiplayer.networkcomms import (
    Message,
    full_qualname,
    import_from_qualname,
)

if TYPE_CHECKING:
    from loveletter_multiplayer.client import LoveletterClient  # noqa


LOGGER = logging.getLogger(__name__)


Connection = "LoveletterClient._ServerConnectionManager"


class RemoteGameShadowCopy(loveletter.game.Game):
    def __init__(self, players: Sequence[str], connection: Connection, player_id: int):
        """
        Create a local shadow copy of a remote game.

        :param players: Same as for Game.
        :param connection: Client-server connection.
        :param player_id: Player id of the client holding this local copy.
        """
        super().__init__(players)
        self.connection = connection
        self.client_player_id = player_id

    @classmethod
    async def from_connection(cls, connection: Connection):
        # noinspection PyTypeChecker
        message: msg.GameCreated = await connection.expect_message(
            message_type=msg.GameCreated
        )
        LOGGER.info("Remote game created; creating local copy")
        return RemoteGameShadowCopy(
            [p.username for p in message.players], connection, message.player_id
        )

    async def track_remote(self):
        """Wraps around the game event generator to follow remote events."""
        connection = self.connection

        # Since async generators don't support yield from, the `handle` hierarchy of
        # multi-methods is specified as follows:
        #   0. potentially communicate to the server or do other handling
        #   1. yield the event (or a transformed event) to the caller
        #   2. receive the response from the caller (same yield expression as 1.)
        #   3. potentially communicate to the server or do other handling
        #   4. yield the final response back
        #   5. the loop below sends that to the core game loop
        #   6. upon success, the handler is advanced again so that it can finalize
        #      things (e.g. by communicating the choice to the server)
        #   7. the handler finishes, raising a StopAsyncIteration

        @multimethod
        async def handle(e: gev.GameEvent):
            raise NotImplementedError(e)
            yield  # noqa

        @handle.register
        async def handle(e: gev.GameResultEvent):
            # just show it to the caller
            yield e
            yield None

        @handle.register
        async def handle(e: gnd.GameNodeState):
            # Make sure that the one received from the server is equivalent
            await self._sync_with_server(e)
            yield e
            yield None

        @handle.register
        async def handle(e: loveletter.game.PlayingRound):
            # hack to ensure same deck at the start of each round
            message = await connection.get_game_message(
                message_type=msg.RoundInitMessage
            )
            deck = message.deck
            LOGGER.debug("Synchronizing initial deck to %s", deck)
            game_round = self.current_round
            game_round.deck = deck
            yield e
            yield None

        @handle.register
        async def handle(e: gev.GameInputRequest):
            raise NotImplementedError(e)
            yield  # noqa

        @handle.register
        async def handle(e: gev.ChoiceEvent):
            # default action for a choice event: only ask host
            if connection.client.is_host:
                await self._sync_with_server(e)
                ans = yield e
                choice = ans.to_serializable()
                yield ans
                await self._communicate_choice(type(ans), choice)
            else:
                yield RemoteEvent(
                    wrapped=e, description="Host is choosing who goes first"
                )
                yield await self._set_choice_from_remote(e)

        @handle.register
        async def handle(e: rnd.PlayerMoveChoice):
            current_player_id = self.current_round.current_player.id
            username = self.players[current_player_id].username
            if self.client_player_id == current_player_id:
                await self._sync_with_server(e)
                ans = yield e
                choice = ans.to_serializable()
                yield ans
                await self._communicate_choice(type(ans), choice)
            else:
                yield RemoteEvent(
                    wrapped=e, description=f"Player {username} is making a move"
                )
                yield (await self._set_choice_from_remote(e))

        @handle.register
        def handle(e: move.ChoiceStep):
            # fmt:off
            return handle[rnd.PlayerMoveChoice, ](e)
            # fmt:on

        asyncio.current_task().set_name(f"game<{self.connection.client.username}>")
        gen = self.play()
        event = next(gen)
        while True:
            LOGGER.debug("Local game generated event: %s", event)

            # async generators don't support async "yield from" yet
            # so have to do this; see comment above
            handle_gen = handle(event)  # noqa
            transformed = await handle_gen.asend(None)
            LOGGER.debug("Yielding to caller: %s", transformed)
            answer = yield transformed
            asyncio.current_task().set_name(f"game<{self.connection.client.username}>")
            LOGGER.debug("Caller answered with %s", answer)
            answer = await handle_gen.asend(answer)

            # try sending answer to local game loop
            LOGGER.debug("Sending answer to local game: %s", answer)
            try:
                event = gen.send(answer)  # noqa
            except StopIteration as end:
                results = end.value
                break

            # commit the answer
            try:
                await handle_gen.asend(None)
            except StopAsyncIteration:
                pass

        # Ideally: `return results`; but async generators don't support return values
        # yet, so we use a bare return and let the caller retrieve the results:
        return

    async def _set_choice_from_remote(self, event: gev.ChoiceEvent) -> gev.ChoiceEvent:
        LOGGER.debug("Awaiting on remote to relay choice for %s", event)
        message = await self.connection.get_game_message(
            message_type=msg.FulfilledChoiceMessage
        )
        # fmt:off
        assert import_from_qualname(message.choice_class) is type(event), \
            f"Client fell out of sync: client: {event}, server: {message.choice_class}"
        # fmt:on
        event.set_from_serializable(message.choice)
        LOGGER.debug("Remote player chose: %s", event)
        return event

    @multimethod
    async def _sync_with_server(self, event: gev.GameEvent) -> Message:
        """Wait for the server to send the same event to make sure client is in sync."""
        raise NotImplementedError(event)

    @_sync_with_server.register
    async def _sync_with_server(self, event: gnd.GameNodeState):
        LOGGER.debug("Syncing state with server: %s", event)
        message = await self.connection.get_game_message(
            message_type=msg.GameNodeStateMessage
        )
        # fmt:off
        assert message.state == event, \
            f"Client fell out of sync: client: {event}, server: {message.state}"
        # fmt:on
        return message

    @_sync_with_server.register
    async def _sync_with_server(self, event: gev.GameInputRequest):
        LOGGER.debug("Syncing input request with server: %s", event)
        message = await self.connection.get_game_message(
            message_type=msg.GameInputRequestMessage
        )
        # fmt:off
        assert self._requests_are_equivalent(event, message.request), \
            f"Client fell out of sync: client: {event}, server: {message.request}"
        # fmt:on
        return message

    @_sync_with_server.register
    async def _sync_with_server(self, event: rnd.PlayerMoveChoice):
        # "super" call to reuse code from _sync_with_server for GameInputRequest:
        super_func = self._sync_with_server.__func__[object, gev.GameInputRequest]
        message = await super_func(self, event)
        assert await self._check_player_hands_are_in_sync()
        return message

    async def _communicate_choice(
        self, choice_class: Type[gev.ChoiceEvent], choice: gev.Serializable
    ):
        """Communicate a local choice back to the server."""
        message = msg.FulfilledChoiceMessage(full_qualname(choice_class), choice)
        await self.connection.send_message(message)

    @staticmethod
    @multimethod
    def _requests_are_equivalent(
        local: gev.GameInputRequest, remote: gev.GameInputRequest
    ):
        return remote == local

    @staticmethod
    @_requests_are_equivalent.__func__.register  # need to un-wrap the static method
    def _requests_are_equivalent(local: move.ChoiceStep, remote: move.ChoiceStep):
        return (
            remote.player == local.player
            # can only check type due to a serialization/deserialization defect
            # (the card instances won't be the same object)
            and CardType(remote.card_played) == CardType(local.card_played)
        )

    async def _check_player_hands_are_in_sync(self) -> bool:
        # noinspection PyTypeChecker
        response: msg.DataMessage = await self.connection.request(
            msg.ReadRequest("game.current_round.current_player.hand")
        )
        player = self.current_round.current_player
        username = self.players[player.id].username
        local_hand = list(map(CardType, player.hand))
        remote_hand = list(map(CardType, response.data))
        # fmt: off
        assert local_hand == remote_hand, \
            f"Client and server fell out of sync: {username}'s hand: " \
            f"local: {local_hand}, remote: {remote_hand}"
        # fmt: on
        return True


@dataclass(frozen=True)
class RemoteEvent(gev.GameEvent):
    """Indicates that the client is currently waiting on something on the remote end."""

    wrapped: gev.GameEvent  #: the original event being handled remotely; read only
    description: str
