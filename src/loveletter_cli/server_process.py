import abc
import logging
import multiprocessing
import subprocess
import sys
import typing as tp

from loveletter_cli.data import UserInfo
from loveletter_cli.utils import running_as_pyinstaller_executable


LOGGER = logging.getLogger(__name__)


class ServerProcess(metaclass=abc.ABCMeta):
    """Deals with the creation of the server process in the host session."""

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

    def __init__(
        self,
        hosts: tp.Tuple[str, ...],
        port: int,
        host_user: UserInfo,
        show_logs: bool = False,
    ):

        """
        Configure the server process.

        :param hosts: Host IP/name to bind the server to, or a sequence of such items.
        :param port: Port number to bind the server to.
        :param host_user: Host user info.
        :param show_logs: Whether to show the server's logs. If True,
            it will try to spawn a separate console window, and default to showing
            the logs in the same console as the parent process otherwise.
        """
        self.hosts = hosts
        self.port = port
        self.host_user = host_user
        self.show_logs = show_logs

    @abc.abstractmethod
    def start(self):
        """Start the process."""
        pass

    @abc.abstractmethod
    def join(self, timeout: tp.Optional[int] = None):
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

    def join(self, timeout: tp.Optional[int] = None):
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

        logging_level = (
            LOGGER.getEffectiveLevel() if show_logs else logging.CRITICAL + 1
        )
        self._process = multiprocessing.Process(
            target=loveletter_cli.server_script.main,
            kwargs=dict(
                logging_level=logging_level,
                host=self.hosts,
                port=self.port,
                party_host_username=self.host_user.username,
            ),
            daemon=True,
        )

    def start(self):
        self._process.start()

    def join(self, timeout: tp.Optional[int] = None):
        self._process.join(timeout)
