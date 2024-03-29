import asyncio
import itertools as itt
import logging
import logging.handlers
import pathlib
import typing


def setup_logging(
    level,
    file_path: typing.Optional[pathlib.Path] = None,
) -> None:
    """
    Setup logging for the loveletter_cli application.

    :param level: Logging level.
    :param file_path: Path of file to which to output logs. None means output to stderr.
    """
    logging.setLogRecordFactory(CustomLogRecord)
    root = logging.getLogger()
    root.setLevel(level)
    # noinspection SpellCheckingInspection
    formatter = CustomFormatter(
        fmt="{asctime} | {levelname:^8} | {origin:75.75} | {message}",
        style="{",
    )
    if file_path is not None:
        handler = logging.handlers.TimedRotatingFileHandler(
            file_path, when="midnight", backupCount=2
        )
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.handlers.clear()
    root.addHandler(handler)


class TruncateAfterMaxWidthString(str):
    def __format__(self, format_spec: str):
        if (idx := format_spec.rfind(".")) != -1:
            precision = "".join(itt.takewhile(str.isdigit, format_spec[idx + 1 :]))
            format_no_precision = (
                format_spec[:idx] + format_spec[idx + 1 + len(precision) :]
            )
            precision = int(precision)
            formatted = super().__format__(format_no_precision)
            if len(formatted) > precision:
                formatted = formatted[: precision - 3] + "..."
            return formatted
        else:
            return super().__format__(format_spec)


class CustomLogRecord(logging.LogRecord):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.task = task = asyncio.current_task()
        except RuntimeError:
            self.task = task = None

        if task:
            self.taskName = task.get_name()
            origin = f"[{self.threadName}::{self.taskName}] {self.name}"
        else:
            self.taskName = None
            origin = f"[{self.threadName}] {self.name}"
        self.origin = TruncateAfterMaxWidthString(origin)


class CustomFormatter(logging.Formatter):
    default_time_format = "%H:%M:%S"
