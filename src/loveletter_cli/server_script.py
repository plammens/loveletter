import argparse
import asyncio
import logging

from loveletter_multiplayer import LoveletterPartyServer
from loveletter_multiplayer.logging import setup_logging


def main(logging_level: int, **kwargs):
    setup_logging(logging_level)
    server = LoveletterPartyServer(**kwargs)
    asyncio.run(server.run_server())


def define_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m loveletter_cli.server_script")
    parser.add_argument("host", nargs="+")
    parser.add_argument("port", type=int)
    parser.add_argument("party_host_username")
    parser.add_argument(
        "--logging", type=int, default=logging.INFO, dest="logging_level"
    )
    return parser


if __name__ == "__main__":
    main(**vars(define_cli().parse_args()))
