#!/usr/bin/env python3
"""
Import every node module with CPython, outside the browser.

``python -m juturna validate`` resolves a node type by importing its module,
and so would a pytest of the node: a node must import on desktop, which means
``js`` and ``pyodide.*`` are imported inside the functions that use them.

Usage, with juturna (and numpy) importable:
    python build/check_nodes.py [FOLDER ...]

It checks the nodes under each FOLDER (default: ``examples`` and
``test/plugins``), found as ``build.py`` finds them: a folder ``_<name>`` with
a ``config.toml`` and a ``<name>.py``.
"""

import importlib.util
import os
import pathlib
import sys
import traceback

from build import JUTURNA_VERSION
from build import ROOT
from build import _node_folders
from build import _register


def main():
    """Import every node and report the ones that fail."""
    try:
        import juturna  # noqa: F401
    except ImportError:
        sys.exit(
            'error: check imports the nodes with juturna, which is not '
            'installed (it needs Python 3.12 or later): '
            f'pip install juturna=={JUTURNA_VERSION} numpy'
        )

    folders = [pathlib.Path(arg) for arg in sys.argv[1:]] or [
        ROOT / 'examples',
        ROOT / 'test' / 'plugins',
    ]
    failed = 0

    for folder in folders:
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
                print(f'FAIL {os.path.relpath(node)}', file=sys.stderr)
                traceback.print_exc()
            else:
                print(f'ok   {os.path.relpath(node)} ({cls})')

    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
