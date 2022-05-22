import abc
import atexit
import contextlib
import dataclasses
import logging
import multiprocessing
import subprocess
import sys
import typing as tp

from loveletter_cli.data import UserInfo
from loveletter_cli.utils import running_as_pyinstaller_executable


LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(eq=False)
class ServerProcess(contextlib.AbstractContextManager, metaclass=abc.ABCMeta):
    """
    Deals with the creation of the server process in the host session.

    When used as a context manager, entering the context starts the process
    and exiting the context tries to join the process.
    If joining times out, the subclass ensures that the process is killed in
    some way before the main process exits (to avoid an orphaned server process).

    - ``hosts``: Host IP/name to bind the server to, or a sequence of such items.
    - ``port``: Port number to bind the server to.
    - ``host_user``: User info of the host player.
    - ``show_logs``: Whether to show the server's logs. If True,
        it will try to spawn a separate console window, and default to showing
        the logs in the same console as the parent process otherwise.
    """

    @staticmethod
    def new(*args, show_logs: bool = False, **kwargs) -> "ServerProcess":
        """
        Create a ServerProcess of the appropriate subclass given show_logs.
        """
        if (
            show_logs
            and hasattr(subprocess, "CREATE_NEW_CONSOLE")  # only supported on Windows
            and not running_as_pyinstaller_executable()
        ):
            return NewConsoleServerProcess(*args, **kwargs)
        else:
            return MultiprocessingServerProcess(*args, **kwargs, show_logs=show_logs)

    hosts: tp.Tuple[str, ...]
    port: int
    host_user: UserInfo
    show_logs: bool = False

    def __enter__(self):
        self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            LOGGER.info("Waiting on server process to end")
        else:
            LOGGER.warning(
                "Waiting on server process to end after unhandled exception",
                exc_info=(exc_type, exc_val, exc_tb),
            )
        self.join(timeout=5)

    @abc.abstractmethod
    def start(self):
        """Start the process."""
        LOGGER.debug(f"Starting server process: %s", self)

    @abc.abstractmethod
    def join(self, timeout: tp.Optional[float] = None):
        """Wait for the process to finish, with the given timeout."""
        pass


class NewConsoleServerProcess(ServerProcess):
    def __init__(
        self,
        hosts: tp.Tuple[str, ...],
        port: int,
        host_user: UserInfo,
    ):
        super().__init__(hosts, port, host_user, show_logs=True)

        self._process: tp.Optional[subprocess.Popen] = None

    def start(self):
        super().start()

        assert self.show_logs

        # fmt: off
        self._process = subprocess.Popen(
            args=[
                sys.executable, "-m", "loveletter_cli.server_script",
                *self.hosts,
                str(self.port),
                self.host_user.username,
                "--logging", str(min(LOGGER.getEffectiveLevel(), logging.INFO)),
            ],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        # fmt: on

        # ensure process doesn't get orphaned (no daemon= option in Popen)
        atexit.register(self._process.wait)  # reap zombie process
        atexit.register(self._process.kill)

    def join(self, timeout: tp.Optional[float] = None):
        self._process.wait(timeout)


class MultiprocessingServerProcess(ServerProcess):
    def __init__(
        self,
        hosts: tp.Tuple[str, ...],
        port: int,
        host_user: UserInfo,
        show_logs: bool = False,
    ):
        import loveletter_cli.server_script

        super().__init__(hosts, port, host_user, show_logs)

        logging_level = LOGGER.getEffectiveLevel()
        self._process = multiprocessing.Process(
            target=loveletter_cli.server_script.main,
            kwargs=dict(
                show_logs=show_logs,
                logging_level=logging_level,
                host=self.hosts,
                port=self.port,
                party_host_username=self.host_user.username,
            ),
            daemon=True,
        )

    def start(self):
        super().start()
        self._process.start()

    def join(self, timeout: tp.Optional[float] = None):
        self._process.join(timeout)
