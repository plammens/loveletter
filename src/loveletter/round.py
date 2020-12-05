import abc
import enum
import itertools as itt
import operator
import random
from typing import Optional, Sequence, TYPE_CHECKING

import more_itertools as mitt
import valid8

from loveletter.cardpile import Deck, DiscardPile
from loveletter.player import Player

if TYPE_CHECKING:
    from loveletter.cards import Card


class RoundState(metaclass=abc.ABCMeta):
    class Type(enum.Enum):
        INIT = enum.auto()
        TURN = enum.auto()
        ROUND_END = enum.auto()

    type: Type
    current_player: Optional[Player]

    def __init__(self, type_: Type, current_player: Optional[Player]):
        self.type = type_
        self.current_player = current_player


class InitialState(RoundState):
    def __init__(self):
        super().__init__(RoundState.Type.INIT, None)


class Turn(RoundState):
    """Represents a single turn; acts as a context manager activated during a move"""

    class Stage(enum.Enum):
        START = enum.auto()
        IN_PROGRESS = enum.auto()
        COMPLETED = enum.auto()

    stage: Stage

    def __init__(self, current_player: Player):
        super().__init__(RoundState.Type.TURN, current_player)
        self.stage = Turn.Stage.START

    def __enter__(self):
        valid8.validate(
            "turn.stage",
            self.stage,
            equals=Turn.Stage.START,
            help_msg=f"Can't start another move; turn is already {self.stage.name}",
        )
        self.stage = Turn.Stage.IN_PROGRESS

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stage = Turn.Stage.COMPLETED if exc_type is None else Turn.Stage.START


class RoundEnd(RoundState):
    winner: Player

    def __init__(self, winner: Player):
        super().__init__(RoundState.Type.ROUND_END, None)
        self.winner = winner


class Round:
    players: Sequence[Player]
    deck: Deck
    discard_pile: DiscardPile
    state: RoundState

    def __init__(self, num_players: int):
        valid8.validate(
            "num_players", num_players, instance_of=int, min_value=2, max_value=4
        )
        self.players = [Player(self, i) for i in range(num_players)]
        self.deck = Deck.from_counts()
        self.discard_pile = DiscardPile([])
        self.state = InitialState()

    @property
    def num_players(self):
        return len(self.players)

    @property
    def started(self):
        return self.state.type != RoundState.Type.INIT

    @property
    def ended(self):
        return self.state.type == RoundState.Type.ROUND_END

    @property
    def current_player(self) -> Optional[Player]:
        return self.state.current_player

    @property
    def living_players(self) -> Sequence[Player]:
        """The subsequence of living players."""
        return [p for p in self.players if p.alive]

    def deal_card(self, player: Player) -> "Card":
        """Deal a card to a player from the deck and return the dealt card."""
        valid8.validate(
            "player",
            player,
            is_in=self.players,
            help_msg=f"Can't deal card to outside player",
        )
        player.give(card := self.deck.take())
        return card

    def start(self) -> Turn:
        """Initialise the round: hand out one card to each player and start a turn."""
        for player in self.players:
            self.deal_card(player)
        self.state = turn = Turn(random.choice(self.players))
        return turn

    @valid8.validate_arg("self", started.fget, help_msg="Round hasn't started yet")
    def next_turn(self) -> RoundState:
        """Advance to the next turn."""
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
        next_player = mitt.first_true(
            itt.islice(itt.cycle(self.players), current.id + 1, None),
            pred=operator.attrgetter("alive"),
        )
        assert next_player is not None
        # TODO: deal card to player
        self.state = Turn(next_player)
        return self.state

    def _reached_end(self) -> bool:
        """Whether this round has reached to an end"""
        return len(self.living_players) == 1

    def _finalize_round(self) -> RoundEnd:
        self.state = end = RoundEnd(winner=self.living_players[0])
        return end
