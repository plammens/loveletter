import logging

from loveletter_multiplayer.logging import setup_logging
from loveletter_multiplayer.server import LoveletterPartyServer
from loveletter_multiplayer.utils import StoppableAsyncioThread


HOST = ""
PORT = 48888


def start_server_thread(server):
    server_thread = StoppableAsyncioThread(
        name="ServerThread", target=server.run_server
    )
    server_thread.start()
    return server_thread


def main():
    setup_logging(logging.DEBUG)
    server = LoveletterPartyServer(HOST, PORT, "Host")
    server_thread = start_server_thread(server)
    server_thread.join()


if __name__ == "__main__":
    main()
