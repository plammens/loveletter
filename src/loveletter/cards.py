import abc
import typing
from typing import ClassVar, Generator

import valid8

from loveletter.move import MoveStep

if typing.TYPE_CHECKING:
    from loveletter.player import Player


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
        """
        pass

    # noinspection PyMethodMayBeStatic
    def _validate_move(self, owner: "Player") -> None:
        valid8.validate("owner", owner)


class Spy(Card):
    value = 0

    def play(self, owner: "Player") -> Generator[MoveStep, MoveStep, None]:
        self._validate_move(owner)


class Guard(Card):
    value = 1

    def play(self, owner: "Player") -> Generator[MoveStep, MoveStep, None]:
        self._validate_move(owner)


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
