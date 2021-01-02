"""
Algorithm to recursively apply a function to a composite object.

Dependencies:
  - multimethod (https://pypi.org/project/multimethod/)
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

import copy
import dataclasses
import itertools
import warnings
from typing import Any, Callable, Dict, List, TypeVar

import multimethod
from multimethod import isa

from loveletter_multiplayer.utils import compute_stacklevel, instance_attributes


class RecursionWarning(UserWarning):
    pass


T = TypeVar("T")


def recursive_apply(
    obj: T, predicate: Callable[[Any], bool], function: Callable[[Any], Any]
) -> T:
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
    raise_if_modified: Dict[int, RecursionError] = {}
    # LIFO stack of objects being processed (id(o): o); used to detect reference cycles
    processing: Dict[int, Any] = {}

    def apply(o: Any, patch_func: Callable[[Any], None] = None):
        if id(o) in processing:
            # there is a reference cycle; we try to deal with it by returning a
            # placeholder for now and leaving a memo to remember updating this
            # reference when the referred object has been fully processed too

            cycle = " --> ".join(map(repr, itertools.chain(processing.values(), [o])))
            stacklevel = compute_stacklevel(public_call_site=recursive_apply)
            warnings.warn(
                f"Attempting to resolve detected cycle "
                f"(this might have undesired side effects): {cycle}",
                category=RecursionWarning,
                stacklevel=stacklevel,
            )
            if patch_func is None:
                # no patch function available; can't deal with the cyclic reference
                exc = RecursionError(
                    f"Cycle detected and I'm not able to deal with it: {cycle}"
                )
                raise_if_modified[id(o)] = exc
                return o

            patches.setdefault(id(o), []).append(patch_func)
            return cyclic_reference_placeholder

        processing[id(o)] = o
        try:
            if id(o) in processed:
                maybe_transformed = processed[id(o)]
            else:
                maybe_transformed = _do_apply(o)
                processed[id(o)] = maybe_transformed

            if (
                maybe_transformed is not o
                and (exc := raise_if_modified.get(id(o), None)) is not None
            ):
                raise exc  # noqa

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
