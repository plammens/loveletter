import logging

from loveletter_multiplayer.logging import setup_logging


def main(logging_level: int = logging.INFO):
    setup_logging(logging_level)
