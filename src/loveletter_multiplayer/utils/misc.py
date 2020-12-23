import asyncio
import contextlib
import enum
import logging
import typing
from collections import namedtuple
from typing import ContextManager, TypeVar


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
