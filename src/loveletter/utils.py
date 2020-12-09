def is_subclass(value, cls):
    try:
        return issubclass(value, cls)
    except TypeError:
        return False
