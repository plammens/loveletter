"""
Metaclass for inner classes in Python.
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


class InnerClassMeta(type):
    """
    Metaclass for inner classes.

    An inner class is a nested class that expects an instance of the outer class as
    the first argument to __new__ and __init__. This metaclass implements the
    descriptor protocol (non-data) for the inner class such that calling the inner
    class through an attribute access on an instance of the outer class will
    automatically pass that instance as the first argument to the constructor of the
    inner class.

    This is similar to Java's inner classes.

    Example:

    >>> class Car:
    ...     class Motor(metaclass=InnerClassMeta):
    ...         def __init__(self, car: "Car"):
    ...             self.car = car
    >>> my_car = Car()
    >>> motor = my_car.Motor()
    >>> motor.car is my_car
    True

    Note: this doesn't attempt to discriminate from which class it is being accessed,
    i.e. it doesn't attempt to validate that it is being accessed from the outer class
    in which it was defined (if any).
    """

    class BoundInnerClass:
        def __init__(self, inner_class, outer_instance):
            self.inner_class = inner_class
            self.outer_instance = outer_instance

        def __repr__(self):
            return (
                f"<bound inner class {self.inner_class.__name__}"
                f" of {self.outer_instance}>"
            )

        def __call__(self, *args, **kwargs):
            return self.inner_class(self.outer_instance, *args, **kwargs)

    def __get__(cls, instance, owner):
        if instance is None:
            return cls  # don't bind to classes, just instances
        return InnerClassMeta.BoundInnerClass(cls, instance)
