# -*- mode: python -*-
# Copyright 2023 Andrea Righi

"""virtme-ng: UI spinner class."""

import sys
import time
import threading
from queue import Queue


class InterceptedStream:
    """Fake stream class used to intercept original sys.stdout and sys.stderr."""

    def __init__(self, queue):
        self.queue = queue

    def write(self, text):
        """Intercept original stream write() and push output to a thread queue."""
        self.queue.put(text)

    def flush(self):
        """Intercept original stream flush() that becomes a no-op."""


class Spinner:
    """A live spinner to keep track of lengthy operations.

    The code block inside the context of a Spinner will have the stdout and
    stderr intercepted, so that the output is properly synchronized with the
    spinner text (no interleaving text).

    If the code is executed in a headless environment, e.g., without a
    valid tty, all features are disabled.

    Example usage:

    >>> from virtme_ng.spinner import Spinner
    ... with Spinner(message='Processing') as spin:
    ...     for i in range(10):
    ...         sys.stderr.write('hello\n')
    ...         time.sleep(1)

    Args:
        message (Optional[str]): an optional, always visible message
    """

    def __init__(self, message=""):
        self.message = message
        self.spinner_str = "▁▂▃▄▅▆▇██▇▆▅▄▃▂▁"
        self.pos = 0

        self.stop_event = threading.Event()
        self.spinner_thread = threading.Thread(target=self._spin)
        self.spinner_thread.daemon = True
        self.original_streams = {}
        self.intercepted_streams = {}
        self.start_time = int(time.time())
        self.is_tty = sys.stdout.isatty()

    def __enter__(self):
        if self.is_tty:
            self.original_streams = {
                "stdout": sys.stdout,
                "stderr": sys.stderr,
            }
            self.intercepted_streams = {
                "stdout": Queue(),
                "stderr": Queue(),
            }
            sys.stdout = InterceptedStream(self.intercepted_streams["stdout"])
            sys.stderr = InterceptedStream(self.intercepted_streams["stderr"])

            self.spinner_thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_tty:
            self.stop_event.set()
            self.spinner_thread.join()
            self._flush_streams()

            sys.stdout = self.original_streams["stdout"]
            sys.stderr = self.original_streams["stderr"]

    def _flush_streams(self):
        stdout = self.intercepted_streams["stdout"]
        stderr = self.intercepted_streams["stderr"]

        orig_stdout = self.original_streams["stdout"]
        orig_stderr = self.original_streams["stderr"]

        for stream, orig_stream in [(stdout, orig_stdout), (stderr, orig_stderr)]:
            while not stream.empty():
                orig_stream.write(stream.get())
                orig_stream.flush()

    def _spinner_line(self):
        self.pos = (self.pos + 1) % len(self.spinner_str)
        spinner = self.spinner_str[self.pos:] + self.spinner_str[:self.pos]
        delta_t = int(time.time()) - self.start_time
        header = f"{spinner[:3]} {self.message} ({delta_t} sec)\033[?25l"
        spacer = f"\r{' ' * len(header)}\r"

        stdout = self.original_streams["stdout"]
        stdout.write(header)
        stdout.flush()

        time.sleep(0.1)
        stdout.write(spacer + "\033[?25h")

    def _spin(self):
        while not self.stop_event.is_set():
            self._flush_streams()
            self._spinner_line()
