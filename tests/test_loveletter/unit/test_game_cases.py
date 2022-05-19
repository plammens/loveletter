PLAYER_LIST_CASES = [
    ("spam", "eggs"),
    ("foo", "bar", "qux"),
    ("Alice", "Bob", "Charlie", "Eve"),
    ("A", "B", "C", "D", "E"),
    ("0", "1", "2", "3", "4", "5"),
]

INVALID_PLAYER_LIST_CASES = [
    (),
    ("a"),
    ("a", "b", "c", "d", "e", "f", "g"),
    ("a", 1, "b"),
]
