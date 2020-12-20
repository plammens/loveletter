"""
A module defining enum union based on the standard library's `enum`.
"""

# MIT License
#
# Copyright (c) 2020 Paolo Lammens
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import enum
import itertools as itt
import operator
from functools import reduce
from typing import Literal, Union

import more_itertools as mitt


AUTO = object()


class UnionEnumMeta(enum.EnumMeta):
    """
    The metaclass for enums which are the union of several sub-enums.

    Union enums have the _subenums_ attribute which is a tuple of the enums forming the
    union.
    """

    # noinspection PyProtectedMember
    @classmethod
    def make_union(
        mcs, *subenums: enum.EnumMeta, name: Union[str, Literal[AUTO], None] = AUTO
    ) -> enum.EnumMeta:
        """
        Create an enum whose set of members is the union of members of several enums.

        Order matters: where two members in the union have the same value, they will
        be considered as aliases of each other, and the one appearing in the first
        enum in the sequence will be used as the canonical member (the aliases will
        be associated to this enum member).

        :param subenums: Sequence of sub-enums to make a union of.
        :param name: Name to use for the enum class. AUTO will result in a combination
                     of the names of all subenums, None will result in "UnionEnum".
        :return: An enum class which is the union of the given subenums.

        Example (using the :func:`enum_union` alias defined below):

        >>> class EnumA(enum.Enum):
        ...    A = 1
        >>> class EnumB(enum.Enum):
        ...    B = 2
        ...    ALIAS = 1
        >>> UnionAB = enum_union(EnumA, EnumB)
        >>> UnionAB.__members__
        mappingproxy({'A': <EnumA.A: 1>, 'B': <EnumB.B: 2>, 'ALIAS': <EnumA.A: 1>})

        >>> list(UnionAB)
        [<EnumA.A: 1>, <EnumB.B: 2>]

        >>> EnumA.A in UnionAB
        True

        >>> EnumB.ALIAS in UnionAB
        True

        >>> isinstance(EnumB.B, UnionAB)
        True

        >>> issubclass(UnionAB, enum.Enum)
        True

        >>> class EnumC(enum.Enum):
        ...    C = 3
        >>> enum_union(UnionAB, EnumC) == enum_union(EnumA, EnumB, EnumC)
        True

        >>> UnionABC = enum_union(UnionAB, EnumC)
        >>> UnionABC.__members__
        mappingproxy({'A': <EnumA.A: 1>,
                      'B': <EnumB.B: 2>,
                      'ALIAS': <EnumA.A: 1>,
                      'C': <EnumC.C: 3>})

        >>> set(UnionAB).issubset(UnionABC)
        True
        """
        subenums = mcs._normalize_subenums(subenums)
        mcs._check_duplicates(subenums)

        class UnionEnum(enum.Enum, metaclass=mcs):
            pass

        union_enum = UnionEnum
        union_enum._subenums_ = subenums

        # If aliases are defined, the canonical member will be the one that appears
        # first in the sequence of subenums; dict union keeps the last key so we have
        # to do it in reverse.
        # Dict union might be inefficient for large numbers of
        # subenums, but this is intended to be used with "manual-scale" numbers of
        # enums (2, 3, 5 or so) and being an operator it's a better match for reduce
        # since it's a pure function and won't mutate any of the dictionaries.
        union_enum._value2member_map_ = value2member_map = reduce(
            operator.or_,  # dict union (PEP 584)
            (subenum._value2member_map_ for subenum in reversed(subenums)),
            {},  # identity element
        )
        # union of the _member_map_'s but using the canonical member always:
        union_enum._member_map_ = member_map = {
            name: value2member_map[member.value]
            for name, member in itt.chain.from_iterable(
                subenum._member_map_.items() for subenum in subenums
            )
        }
        # only include canonical aliases in _member_names_
        union_enum._member_names_ = list(
            mitt.unique_everseen(
                itt.chain.from_iterable(subenum._member_names_ for subenum in subenums),
                key=member_map.__getitem__,
            )
        )

        # set the __name__ attribute of the enum
        if name is AUTO:
            name = (
                "".join(subenum.__name__.removesuffix("Enum") for subenum in subenums)
                + "UnionEnum"
            )
            UnionEnum.__name__ = name
        elif name is not None:
            UnionEnum.__name__ = name
        else:
            pass  # keep default name ("UnionEnum")

        return union_enum

    def __repr__(cls):
        return f"<union enum of {cls._subenums_}>"

    def __instancecheck__(cls, instance):
        return any(isinstance(instance, subenum) for subenum in cls._subenums_)

    def __eq__(cls, other):
        """Equality based on the tuple of subenums (order-sensitive)."""
        if not isinstance(other, UnionEnumMeta):
            return NotImplemented
        return cls._subenums_ == other._subenums_

    @classmethod
    def _normalize_subenums(mcs, subenums):
        """Remove duplicate subenums and flatten nested unions"""
        # we will need to collapse at most one level of nesting, with the inductive
        # hypothesis that any previous unions are already flat
        subenums = mitt.collapse(
            (e._subenums_ if isinstance(e, mcs) else e for e in subenums),
            base_type=enum.EnumMeta,
        )
        subenums = mitt.unique_everseen(subenums)
        return tuple(subenums)

    @classmethod
    def _check_duplicates(mcs, subenums):
        names, duplicates = set(), set()
        for subenum in subenums:
            for name in subenum.__members__:
                (duplicates if name in names else names).add(name)
        if duplicates:
            raise ValueError(f"Found duplicate member names: {duplicates}")


# alias
enum_union = UnionEnumMeta.make_union


def extend_enum(base_enum: enum.EnumMeta):
    """
    Enum class decorator to "extend" an enum by computing the union with the given enum.

    This is equivalent to ``ExtendedEnum = enum_union(BaseEnum, Extension)``, where
    ``BaseEnum`` is the ``base_enum`` parameter and ``Extension`` is the decorated
    enum.

    :param base_enum: The base enum to be extended.
    :return: The union of ``base_enum`` and the decorated enum.


    Example:

    >>> class BaseEnum(enum.Enum):
    ...     A = 1
    ...
    >>> @extend_enum(BaseEnum)
    ... class ExtendedEnum(enum.Enum):
    ...     ALIAS = 1
    ...     B = 2
    >>> ExtendedEnum.__members__
    mappingproxy({'A': <BaseEnum.A: 1>,
                  'ALIAS': <BaseEnum.A: 1>,
                  'B': <ExtendedEnum.B: 2>})
    """

    def decorator(extension_enum: enum.EnumMeta):
        return enum_union(base_enum, extension_enum)

    return decorator
