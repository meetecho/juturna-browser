#!/usr/bin/env python3
"""Import every node module with CPython, outside the browser.

``python -m juturna validate`` resolves a node type by importing its module,
and so would a pytest of the node: a node must import on desktop, which means
``js`` and ``pyodide.*`` are imported inside the functions that use them.

Usage, with juturna (and numpy) importable:
    python build/check_nodes.py

It checks the nodes under ``examples`` and ``test/plugins``, found as
``build.py`` finds them: a folder ``_<name>`` with a ``config.toml`` and a
``<name>.py``.
"""

import importlib.util
import sys
import traceback

from build import ROOT
from build import _node_folders
from build import _register


def main():
    failed = 0

    for folder in (ROOT / 'examples', ROOT / 'test' / 'plugins'):
        for node in _node_folders(folder):
            module = node.name[1:]
            (cls,) = _register(node)
            spec = importlib.util.spec_from_file_location(
                module, node / f'{module}.py'
            )

            try:
                spec.loader.exec_module(importlib.util.module_from_spec(spec))
            except Exception:
                failed += 1
                print(f'FAIL {node.relative_to(ROOT)}', file=sys.stderr)
                traceback.print_exc()
            else:
                print(f'ok   {node.relative_to(ROOT)} ({cls})')

    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
