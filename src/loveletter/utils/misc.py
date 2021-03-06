import inspect
import itertools
from typing import (
    Any,
    Callable,
    Collection,
    Iterable,
    Iterator,
    List,
    Optional,
    Type,
    TypeVar,
)


def safe_is_subclass(value, cls):
    try:
        return issubclass(value, cls)
    except TypeError:
        return False


T = TypeVar("T")


def cycle_from(
    iterable: Iterable[T], from_item: T, times: Optional[int] = None
) -> Iterator[T]:
    """
    Return a cyclic iterator starting from the first occurrence of an item.

    :param iterable: A finite iterable.
    :param from_item: Object to find in the iterable from which to start cycling.
    :param times: Times to cycle through the whole sequence of elements. None means
                  cycle infinitely.
    :return: A possibly infinite iterator that cycles ``times`` times through the
             elements of ``iterable`` starting from the first occurrence of ``item``.
    """
    it = iter(iterable)
    skipped = list(itertools.takewhile(lambda x: x != from_item, it))
    it = itertools.chain((from_item,), it, skipped)
    if times is not None:
        return itertools.chain.from_iterable(itertools.repeat(it, times))
    else:
        return itertools.cycle(it)


def argmax(iterable: Iterable[T], key: Callable[[T], Any] = None) -> List[T]:
    """
    Get a list of *all* maximal elements in an iterable.

    :param iterable: Iterable of items to search through.
    :param key: Key function to maximize; default is the identity function.
    """
    key = key if key is not None else lambda x: x
    it = iter(iterable)
    if (first := next(it, None)) is None:
        raise ValueError("Empty iterable")
    max_key, args = key(first), [first]

    for x in it:
        if (k := key(x)) > max_key:
            max_key, args = k, [x]
        elif k == max_key:
            args.append(x)

    return args


def minirepr(obj) -> str:
    """Returns a repr string for a given object like object.__repr__ but shorter"""
    return f"<{type(obj).__name__} 0x{id(obj):X}>"


_T = TypeVar("_T")


def collect_subclasses(base_class: Type[_T], module) -> Collection[Type[_T]]:
    def is_strict_subclass(obj):
        return (
            inspect.isclass(obj)
            and issubclass(obj, base_class)
            and obj is not base_class
        )

    return [m for n, m in inspect.getmembers(module, is_strict_subclass)]
