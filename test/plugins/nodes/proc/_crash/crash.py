"""Test node: relays `after` messages, then its Worker vanishes."""

from js import close

from juturna.components import Node


class Crash(Node):
    def __init__(self, after: int, **kwargs):
        super().__init__(**kwargs)
        self._after = after
        self._seen = 0

    def update(self, message, **kwargs):
        self._seen += 1

        if self._seen > self._after:
            # no error, no goodbye: like a Worker killed by the browser
            close()

        self.transmit(message)
