"""Test node: relays `after` messages, then its Worker vanishes. Its warm-up
keeps the thread busy for `warmup_ms`, as a model being compiled does."""

import time

from js import close

from juturna.components import Node


class Crash(Node):
    def __init__(self, after: int, warmup_ms: int = 0, **kwargs):
        super().__init__(**kwargs)
        self._after = after
        self._warmup_s = warmup_ms / 1000
        self._seen = 0

    def warmup(self):
        end = time.perf_counter() + self._warmup_s

        while time.perf_counter() < end:
            pass

    def update(self, message, **kwargs):
        self._seen += 1

        if self._seen > self._after:
            # no error, no goodbye: like a Worker killed by the browser
            close()

        self.transmit(message)
