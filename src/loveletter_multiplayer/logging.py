import itertools as itt
import logging


def setup_logging(level):
    logging.setLogRecordFactory(CustomLogRecord)
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(
        fmt="{asctime} - {levelname:^8} - {origin:50.50} - {message}",
        style="{",
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.handlers.clear()
    root.addHandler(handler)


class TruncateAfterMaxWidthString(str):
    def __format__(self, format_spec: str):
        if (idx := format_spec.rfind(".")) != -1:
            precision = "".join(itt.takewhile(str.isdigit, format_spec[idx + 1 :]))
            format_no_prec = format_spec[:idx] + format_spec[idx + 1 + len(precision) :]
            precision = int(precision)
            formatted = super().__format__(format_no_prec)
            if len(formatted) > precision:
                formatted = formatted[: precision - 3] + "..."
            return formatted
        else:
            return super().__format__(format_spec)


class CustomLogRecord(logging.LogRecord):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.origin = TruncateAfterMaxWidthString(f"[{self.threadName}] {self.name}")
