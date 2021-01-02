import asyncio
import contextlib
import copy
import dataclasses
import enum
import importlib
import inspect
import logging
import operator
import sys
import threading
import traceback
import types
import typing
import warnings
from collections import namedtuple
from functools import lru_cache
from typing import Any, Callable, ClassVar, Dict, List, Optional, Union

import multimethod
from multimethod import isa


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

    # mapping of sub-object id to the transformed sub-object
    processed: Dict[int, Any] = {}
    # placeholder for cyclic references
    cyclic_reference_placeholder = object()
    # map of referred object id to patch function to update a cyclic reference
    patches: Dict[int, List[Callable[[Any], None]]] = {}
    # LIFO stack of objects being processed (id(o): o); used to detect reference cycles
    processing: Dict[int, Any] = {}

    def apply(o: Any, patch_func: Callable[[Any], None] = None):
        if id(o) in processing:
            # there is a reference cycle; we try to deal with it by returning a
            # placeholder for now and leaving a memo to remember updating this
            # reference when the referred object has been fully processed too
            msg = (
                f"Cycle detected: {' --> '.join(map(str, processing.values()))}"
                f" --> {repr(o)}"
            )
            if patch_func is None:
                # no patch function available; can't deal with the cyclic reference
                raise RecursionError(msg)

            # determine stacklevel for warning
            stacklevel = compute_stacklevel(public_call_site=recursive_apply)
            warnings.warn(msg, category=RecursionWarning, stacklevel=stacklevel)

            patches.setdefault(id(o), []).append(patch_func)
            return cyclic_reference_placeholder

        processing[id(o)] = o
        try:
            if id(o) in processed:
                maybe_transformed = processed[id(o)]
            else:
                maybe_transformed = _do_apply(o)
                processed[id(o)] = maybe_transformed

            # restore the correct value in any cyclic reference placeholders
            if (patch_functions := patches.pop(id(o), None)) is not None:
                # noinspection PyUnboundLocalVariable
                for patch in patch_functions:
                    patch(maybe_transformed)

            return maybe_transformed
        finally:
            processing.popitem()  # relies on Python 3.7+ behaviour

    # _do_apply is overloaded based on whether the object satisfies the predicate first,
    # and its type. Overloads are checked in reverse order of registration.

    @multimethod.overload
    def _do_apply(o):
        # fallback for other objects; do attribute lookup

        def attribute_patch(attr: str):
            def patch_func(maybe_transformed):
                object.__setattr__(attribute_patch.the_object, attr, maybe_transformed)

            return patch_func

        filled_values = {}
        for name, value in instance_attributes(o).items():
            if name.startswith("__"):
                continue
            transformed = apply(value, patch_func=attribute_patch(name))
            if transformed is not value:
                filled_values[name] = transformed
        if not filled_values:
            return o

        if dataclasses.is_dataclass(o):
            transformed = dataclasses.replace(o, **filled_values)
        else:
            obj_copy = copy.copy(o)
            for name, value in filled_values.items():
                setattr(obj_copy, name, value)
            transformed = obj_copy
        attribute_patch.the_object = transformed
        return transformed

    @_do_apply.register
    def _do_apply(o: isa(dict)):
        def key_patch(key: Any):
            def patch_func(maybe_transformed):
                d = key_patch.the_dict
                # warning: this might change the order
                value = d.pop(key)
                d[maybe_transformed] = value

            return patch_func

        def value_patch(key: Any):
            def patch_func(maybe_transformed):
                value_patch.the_dict[key] = maybe_transformed

            return patch_func

        # noinspection PyArgumentList
        transformed = type(o)(
            (apply(k, patch_func=key_patch(k)), apply(v, patch_func=value_patch(v)))
            for k, v in o.items()
        )
        value_patch.the_dict = key_patch.the_dict = transformed

        # "maybe" is because the changes might just be cyclic reference placeholders
        maybe_modified = not all(
            k1 is k2 and v1 is v2
            for (k1, v1), (k2, v2) in zip(o.items(), transformed.items())
        )
        return transformed if maybe_modified else o

    @_do_apply.register
    def _do_apply(o: isa(tuple, list, set, frozenset)):
        if isinstance(o, list):

            def item_patch(index: int):
                def patch_func(maybe_transformed):
                    item_patch.the_list[index] = maybe_transformed

                return patch_func

        else:
            item_patch = lambda i: None  # noqa

        transformed = type(o)(
            apply(x, patch_func=item_patch(i)) for i, x in enumerate(o)
        )
        item_patch.the_list = transformed

        # "maybe" is because the changes might just be cyclic reference placeholders
        maybe_modified = not all(x is y for x, y in zip(o, transformed))
        return transformed if maybe_modified else o

    @_do_apply.register
    def _do_apply(o: predicate):
        return function(o)

    result = apply(obj)
    assert len(patches) == 0
    return result


class RecursionWarning(UserWarning):
    pass


def compute_stacklevel(public_call_site: callable) -> int:
    """Compute the stacklevel necessary to emit a warning at the "public" call site."""
    function = (
        public_call_site
        if isinstance(public_call_site, types.FunctionType)  # noqa
        else public_call_site.__call__
    )
    stacklevel = 2
    frame = sys._getframe()  # noqa
    while frame.f_code is not function.__code__:
        frame = frame.f_back
        stacklevel += 1
    return stacklevel - 1
