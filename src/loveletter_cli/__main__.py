import argparse
import logging

from .main import main


def logging_level(level: str) -> int:
    try:
        level = int(level)
    except ValueError:
        pass

    if isinstance(level, int):
        if level <= 0:
            raise ValueError(f"Level can't be negative: {level}")
        return level
    else:
        try:
            # noinspection PyUnresolvedReferences,PyProtectedMember
            return logging._nameToLevel[level]
        except KeyError:
            raise ValueError(f"Not a valid level name: {level}")


parser = argparse.ArgumentParser(prog="python -m loveletter_cli")
parser.add_argument(
    "--logging",
    "-l",
    type=logging_level,
    default=logging.WARNING,
    dest="logging_level",
    help="Logging level (either a name or a numeric value). Default: WARNING",
)
parsed = parser.parse_args()

main(**vars(parsed))
