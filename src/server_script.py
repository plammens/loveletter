import asyncio
import logging

from loveletter_multiplayer.logging import setup_logging
from loveletter_multiplayer.server import LoveletterPartyServer


HOST = ""
PORT = 48888


def main():
    setup_logging(logging.DEBUG)
    asyncio.run(LoveletterPartyServer(HOST, PORT).run_server())


if __name__ == "__main__":
    main()
