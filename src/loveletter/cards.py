import abc
import enum
import typing
from typing import ClassVar, Dict, Generator

import valid8

import loveletter.move as move
from loveletter.move import CardGuess, MoveStep, OpponentChoice

if typing.TYPE_CHECKING:
    from loveletter.player import Player
    from loveletter.round import Round


class Card(metaclass=abc.ABCMeta):
    value: ClassVar[int]

    @property
    def name(self):
        """Name of the card"""
        return self.__class__.__name__

    @abc.abstractmethod
    def play(self, owner: "Player") -> Generator[MoveStep, MoveStep, None]:
        """
        Play this card from its owner.

        :param owner: Owner of the card; who is playing it.
        :returns: A generator that stops at every step in the move at which some
                  additional input is needed from the player. An instance of MoveStep
                  is yielded, indicating what information it needs; once that gets
                  "filled in" the same object should be sent back to the generator.
                  The generator will yield loveletter.move.DONE to signal when the
                  move has been completed.
        """
        pass

    @classmethod
    def collect_extra_points(cls, game_round: "Round") -> Dict["Player", int]:
        """
        After a round has ended, collect any extra points to award to players.

        This behaviour is defined by each type of card, that's why it's implemented
        as a classmethod.
        """
        assert game_round.ended
        return {}

    # noinspection PyMethodMayBeStatic
    def _validate_move(self, owner: "Player") -> None:
        valid8.validate("owner", owner)

    @staticmethod
    def _yield_step(step):
        completed = yield step
        valid8.validate(
            "completed_step",
            completed,
            custom=lambda s: s is step,
            help_msg=(
                f"Did not receive the same MoveStep that was yielded: "
                f"expected {step}, got {completed}"
            ),
        )
        return completed


class Spy(Card):
    value = 0

    def play(self, owner: "Player") -> Generator[MoveStep, MoveStep, None]:
        self._validate_move(owner)
        game_round = owner.round
        game_round.spy_winner = owner if not hasattr(game_round, "spy_winner") else None
        yield move.DONE

    @classmethod
    def collect_extra_points(cls, game_round: "Round") -> Dict["Player", int]:
        points = super().collect_extra_points(game_round)
        if spy_winner := getattr(game_round, "spy_winner", None):
            points.update({spy_winner: 1})
        return points


class Guard(Card):
    value = 1

    def play(self, owner: "Player") -> Generator[MoveStep, MoveStep, None]:
        self._validate_move(owner)
        opponent = (yield from self._yield_step(OpponentChoice(owner))).choice
        guess = (yield from self._yield_step(CardGuess())).choice
        if type(opponent.hand.card) == guess:
            opponent.eliminate()


class Priest(Card):
    value = 2

    def play(self, owner: "Player") -> Generator[MoveStep, MoveStep, None]:
        self._validate_move(owner)


class Baron(Card):
    value = 3

    def play(self, owner: "Player") -> Generator[MoveStep, MoveStep, None]:
        self._validate_move(owner)


class Handmaid(Card):
    value = 4

    def play(self, owner: "Player") -> Generator[MoveStep, MoveStep, None]:
        self._validate_move(owner)


class Prince(Card):
    value = 5

    def play(self, owner: "Player") -> Generator[MoveStep, MoveStep, None]:
        self._validate_move(owner)


class Chancellor(Card):
    value = 6

    def play(self, owner: "Player") -> Generator[MoveStep, MoveStep, None]:
        self._validate_move(owner)


class King(Card):
    value = 7

    def play(self, owner: "Player") -> Generator[MoveStep, MoveStep, None]:
        self._validate_move(owner)


class Countess(Card):
    value = 8

    def play(self, owner: "Player") -> Generator[MoveStep, MoveStep, None]:
        self._validate_move(owner)


class Princess(Card):
    value = 9

    def play(self, owner: "Player") -> Generator[MoveStep, MoveStep, None]:
        self._validate_move(owner)


class CardType(enum.Enum):
    SPY = Spy
    GUARD = Guard
    PRIEST = Priest
    BARON = Baron
    HANDMAID = Handmaid
    PRINCE = Prince
    CHANCELLOR = Chancellor
    KING = King
    COUNTESS = Countess
    PRINCESS = Princess

    def __eq__(self, other):
        return super().__eq__(CardType(other))
