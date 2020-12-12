import itertools
from typing import Iterable, Iterator, Optional, TypeVar


def is_subclass(value, cls):
    try:
        return issubclass(value, cls)
    except TypeError:
        return False


T = TypeVar("T")


def cycle_from(
    iterable: Iterable[T], item: T, times: Optional[int] = None
) -> Iterator[T]:
    """
    Return a cyclic iterator starting from the first occurrence of an item.

    :param iterable: A finite iterable.
    :param item: Object to find in the iterable from which to start cycling.
    :param times: Times to cycle through the whole sequence of elements. None means
                  cycle infinitely.
    :return: A possibly infinite iterator that cycles ``times`` times through the
             elements of ``iterable`` starting from the first occurrence of ``item``.
    """
    it = iter(iterable)
    skipped = list(itertools.takewhile(lambda x: x != item, it))
    it = itertools.chain((item,), it, skipped)
    if times is not None:
        return itertools.chain.from_iterable(itertools.repeat(it, times))
    else:
        return itertools.cycle(it)
