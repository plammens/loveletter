import logging


def setup_logging(level):
    class CustomLogRecord(logging.LogRecord):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.origin = f"[{self.threadName}] {self.name}"

    logging.setLogRecordFactory(CustomLogRecord)

    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(
        fmt="{asctime} - {levelname:^8} - {origin:50} - {message}",
        style="{",
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.handlers.clear()
    root.addHandler(handler)
