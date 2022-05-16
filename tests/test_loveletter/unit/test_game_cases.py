PLAYER_LIST_CASES = [
    ("spam", "eggs"),
    ("foo", "bar", "qux"),
    ("Alice", "Bob", "Charlie", "Eve"),
]

INVALID_PLAYER_LIST_CASES = [
    (),
    ("a"),
    ("a", "b", "c", "d", "e", "f", "g"),
    ("a", 1, "b"),
]
