import argparse
import asyncio
import logging
import pathlib
import threading

from loveletter_multiplayer import LoveletterPartyServer
from loveletter_multiplayer.logging import setup_logging


def main(*, logging_level: int = logging.INFO, show_logs: bool = False, **kwargs):
    """
    Run the server script.

    :param logging_level: Logging level.
    :param show_logs: Whether to show logs to stderr instead of writing them to a file.
    :param kwargs: Passed to :class:`LoveletterPartyServer` to configure the server.
    """
    threading.current_thread().name = "ServerThread"
    setup_logging(
        logging_level,
        file_path=(None if show_logs else pathlib.Path("./loveletter_cli-server.log")),
    )
    server = LoveletterPartyServer(**kwargs)
    asyncio.run(server.run_server())


def define_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m loveletter_cli.server_script")
    parser.add_argument("host", nargs="+")
    parser.add_argument("port", type=int)
    parser.add_argument("party_host_username")
    parser.add_argument(
        "--timeout",
        dest="host_join_timeout",
        type=float,
        default=None,
        help="Timeout to wait for the host to join. Default is none.",
    )
    parser.add_argument(
        "--logging", type=int, default=argparse.SUPPRESS, dest="logging_level"
    )
    parser.add_argument("--show-logs", action="store_true")
    return parser


if __name__ == "__main__":
    main(**vars(define_cli().parse_args()))
