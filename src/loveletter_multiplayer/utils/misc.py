import asyncio
import contextlib
import enum
import importlib
import logging
import threading
import traceback
import typing
from collections import namedtuple
from functools import lru_cache
from typing import Any, ClassVar, ContextManager, Optional, TypeVar


LOGGER = logging.getLogger(__name__)


T = TypeVar("T", bound=ContextManager)


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
    def _get_member(enum_class: enum.EnumMeta, value: typing.Union[str, typing.Any]):
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
    """Like contextlib.closing but specifically for asyncio.StreamWriter"""
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
    while "." in module_path:
        try:
            module = importlib.import_module(module_path)
            return module, tuple(attrs)
        except ImportError:
            module_path, attr = module_path.rsplit(".", maxsplit=1)
            attrs.append(attr)
            continue
    else:
        raise ImportError(f"Couldn't find the module in {repr(qualname)}")


def format_exception(exc: Exception):
    return traceback.format_exception_only(type(exc), exc)[0]
