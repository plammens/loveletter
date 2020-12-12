import itertools
from typing import Iterable, Iterator, TypeVar


def is_subclass(value, cls):
    try:
        return issubclass(value, cls)
    except TypeError:
        return False


T = TypeVar("T")


def cycle_from(iterable: Iterable[T], item: T) -> Iterator[T]:
    """
    Return a cyclic iterator starting from the first occurrence of an item.

    :param iterable: A finite iterable.
    :param item: Object to find in the iterable from which to start cycling.
    :return: An infinite iterator that cycles through the elements of ``iterable``
             starting from the first occurrence of ``item``.
    """
    it = iter(iterable)
    skipped = list(itertools.takewhile(lambda x: x != item, it))
    return itertools.cycle(itertools.chain((item,), it, skipped))
