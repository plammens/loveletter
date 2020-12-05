import abc
import enum
import functools
import typing
from typing import ClassVar, Dict, Generator

import valid8

from loveletter.move import CardGuess, MoveStep, OpponentChoice

if typing.TYPE_CHECKING:
    from loveletter.player import Player
    from loveletter.round import Round


class Card(metaclass=abc.ABCMeta):
    value: ClassVar[int]
    # TODO: add indicator of number of steps needed for play() method

    def __eq__(self, other):
        # card instances have no state, so just compare the card type
        return CardType(type(self)) == CardType(type(other))

    def __hash__(self):
        return hash(CardType(type(self)))

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
        valid8.validate(
            "completed_step",
            completed,
            custom=lambda s: s.completed,
            help_msg="Received an incomplete move step",
        )
        return completed


class Spy(Card):
    value = 0

    def play(self, owner: "Player") -> Generator[MoveStep, MoveStep, None]:
        self._validate_move(owner)
        game_round = owner.round
        game_round.spy_winner = owner if not hasattr(game_round, "spy_winner") else None
        return
        # noinspection PyUnreachableCode
        yield

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
        owner.immune = True
        return
        # noinspection PyUnreachableCode
        yield


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


@functools.total_ordering
class CardType(enum.Enum):
    def __new__(cls, card_class):
        obj = object.__new__(cls)
        obj._value_ = card_class.value
        return obj

    def __init__(self, card_class):
        self.card_class = card_class

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

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, Card):
            value = type(value)
        return CardType(value.value)

    def __eq__(self, other):
        return super().__eq__(CardType(self._get_value(other)))

    def __hash__(self):
        return self.value

    def __lt__(self, other):
        return self.value < self._get_value(other)

    @staticmethod
    def _get_value(other):
        try:
            if issubclass(other, Card):
                return other.value
        except TypeError:
            pass
        return other
