import asyncio
import logging
import threading
from typing import ClassVar, Optional

from loveletter_multiplayer.logging import setup_logging
from loveletter_multiplayer.server import LoveletterPartyServer


HOST = ""
PORT = 48888


class StoppableAsyncioThread(threading.Thread):
    """
    Stoppable asyncio thread.

    The target callable must be a coroutine function that can be executed with
    ``asyncio.run(target())``.
    """

    logger: ClassVar[logging.Logger] = logging.getLogger("threading")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._args = (self._target_wrapper(self._target),)
        self._kwargs = {"debug": self.logger.getEffectiveLevel() <= logging.DEBUG}
        self._target = asyncio.run

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._target_task = None

    def stop(self):
        if self.loop is None:
            raise RuntimeError("This asyncio thread is not running")
        self.logger.debug("Trying to stop %s", self)
        # cancelling the root task will be enough for the loop to close, because
        # we started it with asyncio.run, which only waits until the given task is done;
        # asyncio takes care of cancelling any other tasks
        self.loop.call_soon_threadsafe(self._target_task.cancel)

    async def _target_wrapper(self, target):
        self._target_task = asyncio.current_task()
        self.loop = asyncio.get_running_loop()
        try:
            await target()
        except asyncio.CancelledError:
            return


def start_server_thread(server):
    server_thread = StoppableAsyncioThread(
        name="ServerThread", target=server.run_server
    )
    server_thread.start()
    return server_thread


def main():
    setup_logging(logging.DEBUG)
    server = LoveletterPartyServer(HOST, PORT, "Anakhand")
    server_thread = start_server_thread(server)
    server_thread.join()


if __name__ == "__main__":
    main()
