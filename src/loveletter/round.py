import abc
import enum
import itertools
import random
from typing import Iterable, List, Optional, Sequence, Set, TYPE_CHECKING

import more_itertools
import valid8

from loveletter.cardpile import Deck, DiscardPile
from loveletter.move import CancelMove
from loveletter.player import Player
from loveletter.utils import argmax, cycle_from

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

    def __repr__(self):
        return "InitialState()"


class Turn(RoundState):
    """Represents a single turn; acts as a context manager activated during a move"""

    class Stage(enum.Enum):
        START = enum.auto()
        IN_PROGRESS = enum.auto()
        COMPLETED = enum.auto()
        INVALID = enum.auto()

    stage: Stage

    def __init__(self, current_player: Player):
        super().__init__(RoundState.Type.TURN, current_player)
        self.stage = Turn.Stage.START

    def __repr__(self):
        current_player = self.current_player
        return f"<Turn({current_player}) [stage={self.stage.name}]>"

    def __enter__(self):
        valid8.validate(
            "turn.stage",
            self.stage,
            equals=Turn.Stage.START,
            help_msg=f"Can't start another move; turn is already {self.stage.name}",
        )
        self.stage = Turn.Stage.IN_PROGRESS

    def __exit__(self, exc_type, exc_val, exc_tb):
        transitions = {
            None: Turn.Stage.COMPLETED,
            GeneratorExit: Turn.Stage.START,
            CancelMove: Turn.Stage.START,
        }
        self.stage = transitions.get(exc_type, Turn.Stage.INVALID)


class RoundEnd(RoundState):
    winners: Set[Player]

    def __init__(self, winners: Iterable[Player]):
        super().__init__(RoundState.Type.ROUND_END, None)
        self.winners = set(winners)

    @property
    def winner(self) -> Player:
        with valid8.validation(
            "winners", self.winners, help_msg="There is more than one winner"
        ):
            return more_itertools.only(self.winners)

    def __repr__(self):
        return f"<RoundEnd(winners={set(map(str, self.winners))})>"


class Round:
    players: List[Player]
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
        self.players = [Player(self, i) for i in range(num_players)]
        self.deck = deck if deck is not None else Deck.from_counts()
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

    def __repr__(self):
        alive, state = len(self.living_players), self.state
        return f"<Round({self.num_players}) [{alive=}, {state=}] at {id(self):#X}>"

    def get_player(self, player: Player, offset: int):
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

    def start(self, first_player: Player = None) -> Turn:
        """
        Initialise the round: hand out one card to each player and start a turn.

        :param first_player: First player that will play in this round. None means
                             choose at random.
        """
        if first_player is None:
            first_player = random.choice(self.players)
        else:
            valid8.validate(
                "first_player",
                first_player,
                is_in=self.players,
                help_msg="Not a player of this round",
            )

        for player in itertools.islice(
            cycle_from(self.players, first_player), None, self.num_players + 1
        ):
            self.deal_card(player)
        self.state = turn = Turn(first_player)
        return turn

    @valid8.validate_arg("self", started.fget, help_msg="Round hasn't started yet")
    def advance_turn(self) -> RoundState:
        """Advance to the next turn (supposing the round is ready to do so)"""
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
        """Whether this round has reached to an end"""
        return len(self.living_players) == 1 or len(self.deck.stack) == 0

    def _finalize_round(self) -> RoundEnd:
        self.state = end = RoundEnd(
            winners=argmax(
                self.living_players,
                key=lambda p: (p.hand.card.value, sum(c.value for c in p.cards_played)),
            )
        )
        return end
