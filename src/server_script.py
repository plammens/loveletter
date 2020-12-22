import asyncio
import logging

from loveletter_multiplayer.logging import setup_logging
from loveletter_multiplayer.server import LoveletterPartyServer


HOST = ""
PORT = 48888


def main():
    setup_logging(logging.DEBUG)
    server = LoveletterPartyServer(HOST, PORT)
    asyncio.run(server.run_server())


if __name__ == "__main__":
    main()
