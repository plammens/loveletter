import abc
import typing

if typing.TYPE_CHECKING:
    from loveletter.player import Player


class Card(metaclass=abc.ABCMeta):
    value: int

    @property
    def name(self):
        """Name of the card"""
        return self.__class__.__name__

    @abc.abstractmethod
    def play(self, owner: Player, target: Player):
        """Play this card against another player"""
        assert owner.game is target.game


class Spy(Card):
    value = 0


class Guard(Card):
    value = 1


class Priest(Card):
    value = 2


class Baron(Card):
    value = 3


class Handmaid(Card):
    value = 4


class Prince(Card):
    value = 5


class Chancellor(Card):
    value = 6


class King(Card):
    value = 7


class Countess(Card):
    value = 8


class Princess(Card):
    value = 9
