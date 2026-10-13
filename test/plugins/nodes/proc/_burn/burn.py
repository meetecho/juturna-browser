"""Test node: keeps the CPU busy for burn_ms per message, then relays it."""

import time

from juturna.components import Node


class Burn(Node):
    def __init__(self, burn_ms: int, **kwargs):
        super().__init__(**kwargs)
        self._burn_s = burn_ms / 1000

    def update(self, message, **kwargs):
        end = time.perf_counter() + self._burn_s

        while time.perf_counter() < end:
            pass

        self.transmit(message)
