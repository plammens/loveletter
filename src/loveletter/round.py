import abc
import enum
import itertools as itt
import operator
from typing import Optional, Sequence

import more_itertools as mitt
import valid8

from loveletter.cardpile import Deck
from loveletter.player import Player


class RoundState(metaclass=abc.ABCMeta):
    class Type(enum.Enum):
        TURN = enum.auto()
        ROUND_END = enum.auto()

    type: Type
    current_player: Optional[Player]

    def __init__(self, type_: Type, current_player: Optional[Player]):
        self.type = type_
        self.current_player = current_player


class Turn(RoundState):
    def __init__(self, current_player: Player):
        super().__init__(RoundState.Type.TURN, current_player)


class RoundEnd(RoundState):
    winner: Player

    def __init__(self, winner: Player):
        super().__init__(RoundState.Type.ROUND_END, None)
        self.winner = winner


class Round:
    players: Sequence[Player]
    deck: Deck
    state: RoundState

    def __init__(self, num_players: int):
        valid8.validate(
            "num_players", num_players, instance_of=int, min_value=2, max_value=4
        )
        self.players = [Player(self, i) for i in range(num_players)]
        self.deck = Deck.from_counts()
        self.state = Turn(self.players[0])

    @property
    def current_player(self) -> Optional[Player]:
        return self.state.current_player

    @property
    def living_players(self) -> Sequence[Player]:
        """The subsequence of living players."""
        return [p for p in self.players if p.alive]

    def next_turn(self) -> RoundState:
        """Advance to the next turn."""
        if self._reached_end():
            return self._finalize_round()

        current = self.current_player
        assert current is not None
        next_player = mitt.first_true(
            itt.islice(itt.cycle(self.players), current.id + 1, None),
            pred=operator.attrgetter("alive"),
        )
        assert next_player is not None
        self.state = Turn(next_player)
        return self.state

    def _reached_end(self) -> bool:
        """Whether this round has reached to an end"""
        return len(self.living_players) == 1

    def _finalize_round(self) -> RoundEnd:
        self.state = end = RoundEnd(winner=self.living_players[0])
        return end
