import abc
import enum
import itertools
import random
from dataclasses import dataclass, field
from typing import FrozenSet, List, Optional, Sequence, TYPE_CHECKING

import more_itertools
import valid8

from loveletter.cardpile import Deck, DiscardPile
from loveletter.gameevent import (
    ChoiceEvent,
    GameEventGenerator,
    GameResultEvent,
)
from loveletter.move import CancelMove
from loveletter.roundplayer import RoundPlayer
from loveletter.utils import argmax, cycle_from

if TYPE_CHECKING:
    from loveletter.cards import Card


@dataclass(frozen=True, eq=False)
class RoundState(GameResultEvent, metaclass=abc.ABCMeta):
    """
    Objects of this class represent the game state of a round.

    A RoundState object can be of one of several types, as specified in
    :class:`RoundState.Type`. The relationship between round state types and subclasses
    of RoundState might not necessarily be one-to-one (but it will always be one-to-*).

    When seen as a :class:`GameResultEvent`, a RoundState instance represents the event
    corresponding to the round entering the state described by said instance.

    The attributes of a RoundState are:
     - ``type``: the type of round state as described above
    """

    class Type(enum.Enum):
        INIT = enum.auto()  # round hasn't started yet
        TURN = enum.auto()  # some player's turn
        ROUND_END = enum.auto()  # round has ended

    type: "RoundState.Type"


@dataclass(frozen=True, eq=False)
class Turn(RoundState):
    """
    Represents a single turn; enforces turn constraints.

    A player can only make a move if it is their turn. Thus trying to run e.g.
    :meth:`RoundPlayer.play_card` when it's not the player's turn will raise an
    error. The round can only move on to the next turn if the previous one has been
    completed.

    It is used as a context manager that is entered when a player begins a move.
    While the context is active, it disallows any player in the round (including the
    one that initiated this move) from starting a new move while this one is still
    being played. If the context is exited with an exception, the turn either gets
    reset to its initial state (so that it can start again) or is set to an error
    state, depending on the type of exception.
    """

    class Stage(enum.Enum):
        START = enum.auto()
        IN_PROGRESS = enum.auto()
        COMPLETED = enum.auto()
        INVALID = enum.auto()

    current_player: RoundPlayer
    type: RoundState.Type = field(default=RoundState.Type.TURN, init=False, repr=False)
    # stage is the only mutable field (as if with the C++ `mutable` modifier)
    stage: Stage = field(default=Stage.START, init=False, repr=False, compare=False)

    def __repr__(self):
        return f"<Turn({self.current_player}) [stage={self.stage.name}]>"

    def __enter__(self):
        valid8.validate(
            "turn.stage",
            self.stage,
            equals=Turn.Stage.START,
            help_msg=f"Can't start another move; turn is already {self.stage.name}",
        )
        self._set_stage(Turn.Stage.IN_PROGRESS)

    def __exit__(self, exc_type, exc_val, exc_tb):
        transitions = {
            None: Turn.Stage.COMPLETED,
            GeneratorExit: Turn.Stage.START,
            CancelMove: Turn.Stage.START,
        }
        self._set_stage(transitions.get(exc_type, Turn.Stage.INVALID))

    def _set_stage(self, stage: Stage):
        # circumvent frozen dataclass for mutable field  ``stage``
        object.__setattr__(self, "stage", stage)


@dataclass(frozen=True)
class RoundEnd(RoundState):
    """
    Represents the final state of the round after it has ended.

    Usually there will be only one winner (which can be accessed through the ``winner``
    property), but sometimes more. In this case, accessing ``winner`` will raise an
    error. Thus one should always check the ``winners`` attribute first.
    """

    winners: FrozenSet[RoundPlayer]
    type: RoundState.Type = field(
        default=RoundState.Type.ROUND_END, init=False, repr=False
    )

    @property
    def winner(self) -> RoundPlayer:
        """Return the only winner of the round; raise an error if more than one."""
        with valid8.validation(
            "winners", self.winners, help_msg="There is more than one winner"
        ):
            return more_itertools.only(self.winners)


class Round:
    """
    A single round of Love Letter.

    Only the number of players and a deck is needed to initialise a Round.
    Instantiating a Round creates a list of :class:`RoundPlayer` s bound to this
    Round object.

    The main attributes/properties that make up the state of a Round are:
     - ``players``: A list of RoundPlayers (a physical player bound to this round).
                    The ID (:attr:`~loveletter.roundplayer.RoundPlayer.id`) of each
                    player corresponds to their index in this list.
     - ``living_players``: A subsequence of ``players`` containing only players that
                           are still alive in this round.
     - ``deck``: The deck cards are drawn from in this round.
     - ``discard_pile``: Central discard pile where discarded cards go.
     - ``state``: The current game state, an instance of :class:`RoundState`.
    """

    players: List[RoundPlayer]
    deck: Deck
    discard_pile: DiscardPile
    state: RoundState

    def __init__(self, num_players: int, deck: Deck = None):
        """
        Initialise a new round.

        :param num_players: Number of players in the round.
        :param deck: Initial deck to start with. None means use the standard deck.
        """

        valid8.validate(
            "num_players", num_players, instance_of=int, min_value=2, max_value=4
        )
        self.players = [RoundPlayer(self, i) for i in range(num_players)]
        self.deck = deck if deck is not None else Deck.from_counts()
        self.discard_pile = DiscardPile([])
        self.state = RoundState(RoundState.Type.INIT)

    @property
    def num_players(self):
        """The total number of players participating in this round."""
        return len(self.players)

    @property
    def started(self):
        """Whether the round has started (first cards dealt and first turn started)."""
        return self.state.type != RoundState.Type.INIT

    @property
    def ended(self):
        """Whether the round has ended."""
        return self.state.type == RoundState.Type.ROUND_END

    @property
    def current_player(self) -> Optional[RoundPlayer]:
        """The player whose turn it currently is, or None if not started or ended."""
        return getattr(self.state, "current_player", None)

    @property
    def living_players(self) -> Sequence[RoundPlayer]:
        """The subsequence of living players."""
        return [p for p in self.players if p.alive]

    def __repr__(self):
        alive, state = len(self.living_players), self.state
        return f"<Round({self.num_players}) [{alive=}, {state=}] at {id(self):#X}>"

    def play(self) -> GameEventGenerator:
        """
        The game event generator for this that runs for the duration of the round.

        This provides a higher-level API to step-by-step methods such as
        :meth:`Round.advance_turn`. See :class:`loveletter.gameevent.GameEvent` for a
        description of game event generators.

        The return value of the generator is the final state of the round (i.e. a
        :class:`RoundEnd` instance).
        """

        def iteration():
            # noinspection PyUnresolvedReferences
            card = (yield from PlayerMoveChoice(self.current_player)).choice
            results = yield from self.current_player.play_card(card)
            yield from results  # results is a tuple

        valid8.validate(
            "started",
            self.started,
            equals=False,
            help_msg="Can't start .play() once the round has already started",
        )
        # noinspection PyUnresolvedReferences
        first_player = (yield from FirstPlayerChoice(self)).choice
        yield self.start(first_player=first_player)
        yield from iteration()
        while not self._reached_end():
            yield self.advance_turn()
            yield from iteration()
        end = self.advance_turn()
        return (end,)

    def get_player(self, player: RoundPlayer, offset: int):
        """
        Get the living player that is ``offset`` turns away from a given player.

        :param player: Reference point.
        :param offset: Offset from given player in number of turns. Can be negative,
                       in which case this searches for players in reverse turn order.
        :return: The requested player object.
        """
        players, living_players = self.players, self.living_players
        valid8.validate(
            "player", player, is_in=players, help_msg="Player is not in this round"
        )
        valid8.validate(
            "living_players",
            living_players,
            min_len=1,
            help_msg="No living players remain",
        )
        if player.alive:
            idx = living_players.index(player)
            return living_players[(idx + offset) % len(living_players)]
        else:
            valid8.validate(
                "offset",
                offset,
                custom=lambda o: o != 0,
                help_msg="Can't get player at offset 0; player itself is not alive",
            )
            idx = player.id
            nearest_living = next(p for p in players[idx:] + players[:idx] if p.alive)
            if offset > 0:
                offset -= 1
            living_idx = living_players.index(nearest_living)
            return living_players[(living_idx + offset) % len(living_players)]

    def next_player(self, player):
        """Get the next living player in turn order"""
        return self.get_player(player, 1)

    def previous_player(self, player):
        """Get the previous living player in turn order"""
        return self.get_player(player, -1)

    def deal_card(self, player: RoundPlayer) -> "Card":
        """Deal a card to a player from the deck and return the dealt card."""
        valid8.validate(
            "player",
            player,
            is_in=self.players,
            help_msg=f"Can't deal card to outside player",
        )
        player.give(card := self.deck.take())
        return card

    def start(self, first_player: RoundPlayer = None) -> Turn:
        """
        Start the round: hand out one card to each player and start the first turn.

        :param first_player: First player that will play in this round. None means
                             choose at random.
        """
        valid8.validate(
            "started", self.started, equals=False, help_msg="Round has already started"
        )
        if first_player is None:
            first_player = random.choice(self.players)
        else:
            valid8.validate(
                "first_player",
                first_player,
                is_in=self.players,
                help_msg="Not a player of this round",
            )

        with valid8.validation(
            "round", self, help_msg="Invalid initial state for starting the round"
        ):
            for player in itertools.islice(
                cycle_from(self.players, first_player), None, self.num_players + 1
            ):
                self.deal_card(player)
            if self._reached_end():
                raise ValueError("End condition true immediately upon starting")

        self.state = turn = Turn(first_player)
        return turn

    @valid8.validate_arg("self", started.fget, help_msg="Round hasn't started yet")
    def advance_turn(self) -> RoundState:
        """Advance to the next turn (supposing it is possible to do so already)."""
        valid8.validate(
            "turn",
            self.state,
            custom=lambda t: t.stage == Turn.Stage.COMPLETED,
            help_msg="Can't start next turn before the previous one is completed",
        )
        if self.ended:
            raise StopIteration
        if self._reached_end():
            return self._finalize_round()

        current = self.current_player
        assert current is not None
        next_player = self.next_player(current)
        assert next_player is not None
        # Reset immunity if needed:
        if next_player.immune:
            next_player.immune = False
        self.deal_card(next_player)
        self.state = Turn(next_player)
        return self.state

    def _reached_end(self) -> bool:
        """Whether this round has reached to an end."""
        return len(self.living_players) == 1 or len(self.deck.stack) == 0

    def _finalize_round(self) -> RoundEnd:
        """End the round and declare the winner(s)."""
        winners = argmax(
            self.living_players,
            key=lambda p: (p.hand.card.value, sum(c.value for c in p.cards_played)),
        )
        self.state = end = RoundEnd(winners=frozenset(winners))
        return end


class FirstPlayerChoice(ChoiceEvent):
    """Let the players chose who goes first."""

    def __init__(self, game_round: Round):
        super().__init__()
        self.round = game_round

    def _validate_choice(self, value):
        valid8.validate(
            "choice",
            value,
            is_in=self.round.players,
            help_msg="Not a player of the round",
        )


class PlayerMoveChoice(ChoiceEvent):
    """Make the player chose a card to play."""

    def __init__(self, player: RoundPlayer):
        super().__init__()
        self.player = player

    def _validate_choice(self, value):
        valid8.validate(
            "choice",
            value,
            is_in=self.player.hand,
            help_msg="Card not in player's hand",
        )
