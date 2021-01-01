import asyncio
import contextlib
import copy
import dataclasses
import enum
import importlib
import inspect
import logging
import operator
import threading
import traceback
import typing
from collections import namedtuple
from functools import lru_cache
from typing import Any, Callable, ClassVar, Dict, Optional, Union


LOGGER = logging.getLogger(__name__)


class SemaphoreWithCount(asyncio.BoundedSemaphore):
    """A semaphore that exposes the current count of concurrent acquisitions."""

    @property
    def count(self) -> int:
        """
        The number of calls to acquire with a pending release.

        If tasks only acquire the semaphore with an ``async with`` statement (or
        manually pair a call to release for each call to acquire), and the semaphore
        isn't used reentrantly,this corresponds to the number of tasks currently holding
        the semaphore.
        """
        # lazy implementation: use the BoundedSemaphore internals:
        # noinspection PyUnresolvedReferences
        return self._bound_value - self._value


class EnumPostInitMixin:
    """Mixin class for dataclasses to ensure enum attributes are enum members."""

    def __post_init__(self):
        annotations = typing.get_type_hints(type(self))
        for name, type_ in annotations.items():
            if not name.startswith("_") and isinstance(type_, enum.EnumMeta):
                # possibly work around frozen dataclass
                value = getattr(self, name)
                member = self._get_member(type_, value)
                object.__setattr__(self, name, member)

    @staticmethod
    def _get_member(enum_class: enum.EnumMeta, value: Union[str, Any]):
        # value has priority over name
        try:
            return enum_class(value)
        except ValueError:
            try:
                return enum_class[value]
            except KeyError:
                raise LookupError(
                    f"Couldn't get the enum member in {enum_class} for {value}"
                ) from None


@contextlib.asynccontextmanager
async def close_stream_at_exit(writer: asyncio.StreamWriter):
    """Like ``contextlib.closing`` but specifically for asyncio.StreamWriter"""
    try:
        yield writer
    finally:
        LOGGER.debug("Closing stream %s", writer)
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionResetError:
            # the underlying transport has already been closed by an exception
            if not writer.transport.is_closing():
                raise


Address = namedtuple("Address", ["host", "port"])


class StoppableAsyncioThread(threading.Thread):
    """
    Stoppable asyncio thread.

    The target callable must be a coroutine function that can be executed with
    ``asyncio.run(target())``.
    """

    logger: ClassVar[logging.Logger] = logging.getLogger("threading")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._args = (self._target_wrapper(self._target, *self._args, **self._kwargs),)
        self._kwargs = {"debug": self.logger.getEffectiveLevel() <= logging.DEBUG}
        self._target = asyncio.run

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._target_task = None

    def stop(self):
        if self.loop is None:
            raise RuntimeError("This asyncio thread is not running")
        self.logger.debug("Trying to stop %s", self)
        # cancelling the root task will be enough for the loop to close, because
        # we started it with asyncio.run, which only waits until the given task is done;
        # asyncio takes care of cancelling any other tasks
        self.loop.call_soon_threadsafe(self._target_task.cancel)

    async def _target_wrapper(self, target, *args, **kwargs):
        self._target_task = asyncio.current_task()
        self.loop = asyncio.get_running_loop()
        try:
            await target(*args, **kwargs)
        except asyncio.CancelledError:
            return


def import_from_qualname(qualname: str) -> Any:
    """
    Import an arbitrary global object accessible from the top-level of a module.

    Raises ImportError if no prefix in the qualname can be imported as a module or
    if any of the nested attribute accesses fails.

    :param qualname: Fully qualified name of the object.
    :return: The loaded object.
    """
    module, attrs = _extract_module_from_qualname(qualname)
    attrs = list(attrs)
    try:
        obj = module
        while attrs:
            obj = getattr(obj, attrs.pop())
        return obj
    except AttributeError as e:
        raise ImportError(qualname) from e


@lru_cache
def _extract_module_from_qualname(qualname: str):
    """
    Split a qualified name into a module and the rest of attributes.

    Starts searching in reversed order (i.e. checking first whether the whole qualname
    is a module path), and stops at the longest prefix of the qualname which can be
    imported as a module. Raises ImportError if no prefix of the given qualname is a
    module.

    :param qualname: Qualified name of the object to import.
    :return: The module object and a LIFO stack of attributes to get one from the other.
    """
    module_path = qualname
    attrs = []
    while module_path:
        try:
            module = importlib.import_module(module_path)
            return module, tuple(attrs)
        except ImportError:
            *_, attr = module_path.rsplit(".", maxsplit=1)
            module_path = _[0] if _ else ""
            attrs.append(attr)
            continue
    else:
        raise ImportError(f"Couldn't find the module in {repr(qualname)}")


def format_exception(exc: Exception):
    return traceback.format_exception_only(type(exc), exc)[0]


def full_qualname(cls) -> str:
    """Return the fully qualified name (including the module) of a class."""
    return ".".join((cls.__module__, cls.__qualname__))


def instance_attributes(obj: Any) -> Dict[str, Any]:
    """Get a name-to-value dictionary of instance attributes of an arbitrary object."""
    try:
        return vars(obj)
    except TypeError:
        pass

    # object doesn't have __dict__, try with __slots__
    try:
        slots = obj.__slots__
    except AttributeError:
        # doesn't have __dict__ nor __slots__, probably a builtin like str or int
        return {}
    # collect all slots attributes (some might not be present)
    attrs = {}
    for name in slots:
        try:
            attrs[name] = getattr(obj, name)
        except AttributeError:
            continue
    return attrs


# noinspection PyPep8Naming,SpellCheckingInspection
class attrgetter:
    """Adds __signature__ to operator.attrgetter for compat. with inspect.signature"""

    def __init__(self, *args, **kwargs):
        self._attrgetter = operator.attrgetter(*args, **kwargs)
        params = [inspect.Parameter("object", kind=inspect.Parameter.POSITIONAL_ONLY)]
        self.__signature__ = inspect.Signature(params)

    def __call__(self, *args, **kwargs):
        return self._attrgetter(*args, **kwargs)

    def __repr__(self):
        return repr(self._attrgetter)

    def __reduce__(self):
        return self._attrgetter.__reduce__()


def recursive_apply(
    obj, predicate: Callable[[Any], bool], function: Callable[[Any], Any]
):
    """
    Recursively apply a function to all sub-objects that satisfy a predicate.

    :return: Shallow copy of the object with replaced sub-objects, or the same object
             unmodified if no sub-objects satisfying the predicate were found.
    """

    processing = {}

    def apply(o):
        if id(o) in processing:
            raise RecursionError(
                f"Cycle detected: {list(processing.values())}, then {repr(o)} again"
            )
        processing[id(o)] = o
        try:
            return _do_apply(o)
        finally:
            processing.popitem()

    def _do_apply(o):
        if predicate(o):
            return function(o)

        elif isinstance(o, (tuple, list, set, frozenset)):
            filled = type(o)(apply(x) for x in o)
            modified = not all(x is y for x, y in zip(o, filled))
            return filled if modified else o

        elif isinstance(o, dict):
            # noinspection PyArgumentList
            filled = type(o)((apply(k), apply(v)) for k, v in o.items())
            modified = not all(
                k1 is k2 and v1 is v2
                for (k1, v1), (k2, v2) in zip(o.items(), filled.items())
            )
            return filled if modified else o

        else:
            filled_values = {}
            for name, attr in instance_attributes(o).items():
                if name.startswith("__"):
                    continue
                filled = apply(attr)
                if filled is not attr:
                    filled_values[name] = filled
            if not filled_values:
                return o

            if dataclasses.is_dataclass(o):
                return dataclasses.replace(o, **filled_values)
            else:
                obj_copy = copy.copy(o)
                for name, value in filled_values.items():
                    setattr(obj_copy, name, value)
                return obj_copy

    return apply(obj)
