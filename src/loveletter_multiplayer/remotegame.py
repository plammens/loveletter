"""
Defines classes to view and interact with shadow copies of remote game objects.

A shadow copy is a local copy of a remote object that is meant to be kept in sync with
the remote object.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Sequence, TYPE_CHECKING, Type

from multimethod import multimethod

import loveletter_multiplayer.networkcomms.message as msg
from loveletter.cards import CardType
from loveletter.game import Game, PlayingRound
from loveletter.gameevent import (
    ChoiceEvent,
    GameEvent,
    GameInputRequest,
    GameResultEvent,
    Serializable,
)
from loveletter.gamenode import GameNodeState
from loveletter.move import ChoiceStep
from loveletter.round import InitRoundState, PlayerMoveChoice
from loveletter_multiplayer.networkcomms import (
    Message,
    dataclasses,
    full_qualname,
    import_from_qualname,
)

if TYPE_CHECKING:
    from loveletter_multiplayer.client import LoveletterClient  # noqa


LOGGER = logging.getLogger(__name__)


Connection = "LoveletterClient.ServerConnectionManager"


class RemoteGameShadowCopy(Game):
    def __init__(self, players: Sequence[str], connection: Connection, player_id: int):
        """
        Create a local shadow copy of a remote game.

        :param players: Same as for Game.
        :param connection: Client-server connection.
        :param player_id: Player id of the client holding this local copy.
        """
        super().__init__(players)
        self.connection = connection
        self.player_id = player_id

    @classmethod
    async def from_connection(cls, connection: Connection):
        # noinspection PyTypeChecker
        message: msg.GameCreated = await connection._expect_message(
            message_type=msg.Message.Type.GAME_CREATED
        )
        LOGGER.info("Remote game created; creating local copy")
        return RemoteGameShadowCopy(
            [p.username for p in message.players], connection, message.player_id
        )

    async def track_remote(self):
        """Wraps around the game event generator to follow remote events."""
        connection = self.connection

        # Since async generators don't support yield from, the `handle` hierarchy of
        # multimethods is specified as follows:
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
        async def handle(e: GameEvent):
            raise NotImplementedError(e)
            yield  # noqa

        @handle.register
        async def handle(e: GameResultEvent):
            # just show it to the caller
            yield e
            yield None

        @handle.register
        async def handle(e: GameNodeState):
            # Make sure that the one received from the server is equivalent
            await self._sync_with_server(e)
            yield e
            yield None

        @handle.register
        async def handle(e: PlayingRound):
            # hack to ensure same deck at the start of each round
            # noinspection PyTypeChecker
            message: msg.GameNodeStateMessage = await connection.get_game_message(
                message_type=Message.Type.GAMENODE_STATE
            )
            LOGGER.debug("Synchronizing initial deck")
            init: InitRoundState = message.state.round.state  # noqa
            # noinspection PyTypeChecker
            response: msg.DataMessage = await connection.request(
                msg.ReadRequest("game.current_round.deck")
            )
            deck = response.data
            game_round = self.current_round
            game_round.deck = deck
            game_round.state = dataclasses.replace(game_round.state, deck=deck)
            yield e
            yield None

        @handle.register
        async def handle(e: GameInputRequest):
            raise NotImplementedError(e)
            yield  # noqa

        @handle.register
        async def handle(e: ChoiceEvent):
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
        async def handle(e: PlayerMoveChoice):
            current_player_id = self.current_round.current_player.id
            username = self.players[current_player_id].username
            if self.player_id == current_player_id:
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
        def handle(e: ChoiceStep):
            # fmt:off
            return handle[PlayerMoveChoice,](e)
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

        # Ideally:
        # return results
        # but cant' have a non-empty return inside async generator, so have to do this:
        exc = StopAsyncIteration()
        exc.value = results
        raise exc

    async def _set_choice_from_remote(self, event: ChoiceEvent) -> ChoiceEvent:
        LOGGER.debug("Awaiting on remote to relay choice for %s", event)
        # noinspection PyTypeChecker
        message: msg.FulfilledChoiceMessage = await self.connection.get_game_message(
            message_type=Message.Type.GAME_INPUT_RESPONSE
        )
        # fmt:off
        assert import_from_qualname(message.choice_class) is type(event), \
            f"Client fell out of sync: client: {event}, server: {message.choice_class}"
        # fmt:on
        event.set_from_serializable(message.choice)
        LOGGER.debug("Remote player chose: %s", event)
        return event

    @multimethod
    async def _sync_with_server(self, event: GameEvent) -> Message:
        """Wait for the server to send the same event to make sure client is in sync."""
        raise NotImplementedError(event)

    @_sync_with_server.register
    async def _sync_with_server(self, event: GameNodeState):
        LOGGER.debug("Syncing state with server: %s", event)
        # noinspection PyTypeChecker
        message: msg.GameNodeStateMessage = await self.connection.get_game_message(
            message_type=Message.Type.GAMENODE_STATE
        )
        # fmt:off
        assert message.state == event, \
            f"Client fell out of sync: client: {event}, server: {message.state}"
        # fmt:on
        return message

    @_sync_with_server.register
    async def _sync_with_server(self, event: GameInputRequest):
        LOGGER.debug("Syncing input request with server: %s", event)
        # noinspection PyTypeChecker
        message: msg.GameInputRequestMessage = await self.connection.get_game_message(
            message_type=Message.Type.GAME_INPUT_REQUEST
        )
        # fmt:off
        assert _requests_are_equivalent(event, message.request), \
            f"Client fell out of sync: client: {event}, server: {message.request}"
        # fmt:on
        return message

    @_sync_with_server.register
    async def _sync_with_server(self, event: PlayerMoveChoice):
        # "super" call:
        message = await self._sync_with_server.__func__[object, GameInputRequest](
            self, event
        )
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
        return message

    async def _communicate_choice(
        self, choice_class: Type[ChoiceEvent], choice: Serializable
    ):
        """Communicate a local choice back to the server."""
        message = msg.FulfilledChoiceMessage(full_qualname(choice_class), choice)
        await self.connection._send_message(message)


@dataclass(frozen=True)
class RemoteEvent(GameEvent):
    """Indicates that the client is currently waiting on something on the remote end."""

    wrapped: GameEvent  #: the original event that is being handled remotely; read only
    description: str


@multimethod
def _requests_are_equivalent(local: GameInputRequest, remote: GameInputRequest):
    return remote == local


@_requests_are_equivalent.register
def _requests_are_equivalent(local: ChoiceStep, remote: ChoiceStep):
    return (
        remote.player == local.player
        # can only check type due to a serialization/deserialization defect
        # (the card instances won't be the same object)
        and CardType(remote.card_played) == CardType(local.card_played)
    )