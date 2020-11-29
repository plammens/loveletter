#!/usr/bin/env python3
import abc


class Card(metaclass=abc.ABCMeta):
    value: int

    @property
    def name(self):
        """Name of the card"""
        return self.__class__.__name__


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
