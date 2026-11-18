#!/usr/bin/env python3
r"""
Build what a Pyodide Worker needs to run Juturna: a wheel of the library and
a zip with the browser nodes, from checkouts of the juturna and juturna-nodes
repositories.

Usage:
    python3 build/build.py --juturna /path/to/juturna \\
        --nodes /path/to/juturna_nodes [--test-plugins] [--plugins DIR ...]

``--juturna`` defaults to the ``JUTURNA_REPO`` environment variable, ``--nodes``
to ``JUTURNA_NODES_REPO``.

Output, in ``dist/``:
    juturna-<version>-py3-none-any.whl   the library, built as it is in the
                                         checkout (uncommitted changes included)
    wheel.txt                            the wheel file name, for bootstrap.js
    plugins.zip                          juturna/nodes/ with the browser nodes,
                                         juturna/extensions/nodes/ with the
                                         others; unpacked into site-packages

``--test-plugins`` adds the nodes under ``test/plugins`` (used by the browser
tests, not part of the library). ``--plugins DIR`` adds the nodes under ``DIR``:
every folder ``_<name>`` with a ``config.toml`` and a ``<name>.py`` is a node
(see examples/video-blur). They are used in a pipeline as
``extensions.nodes.<Class>``.
"""

import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'

# nodes of the juturna-nodes checkout shipped in the bundle
BROWSER_NODES = ['_browser_input', '_browser_output']
TEST_PLUGINS = ROOT / 'test' / 'plugins'
PLUGIN_SUFFIXES = {'.py', '.toml'}
EXTENSIONS = 'juturna/extensions/nodes'

REGISTRY = """# noqa: D104
from juturna.components._node_builder._utils import _lazy_node_loaders


_AVAILABLE_PLUGINS: dict[str, str] = {{
{entries}
}}

__getattr__, __dir__ = _lazy_node_loaders(__name__, _AVAILABLE_PLUGINS)
"""


def build_wheel(juturna: pathlib.Path) -> pathlib.Path:
    """Build the wheel of the juturna checkout into dist/."""
    subprocess.run(
        [
            sys.executable,
            '-m',
            'pip',
            'wheel',
            '--no-deps',
            '-q',
            '-w',
            str(DIST),
            str(juturna),
        ],
        check=True,
    )

    return next(DIST.glob('juturna-*.whl'))


def build_plugins(
    nodes: pathlib.Path, test_plugins: bool, extra: list[pathlib.Path]
) -> pathlib.Path:
    """Zip the browser nodes and the extra plugins into dist/plugins.zip."""
    target = DIST / 'plugins.zip'
    package = nodes / 'src' / 'juturna' / 'nodes'
    registry = {}
    folders = set()

    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as zf:
        # the registry lists every node lazily: importing it loads none
        zf.write(package / '__init__.py', 'juturna/nodes/__init__.py')

        for name in BROWSER_NODES:
            _add(zf, package / name, package, 'juturna/nodes')

        for folder in [*([TEST_PLUGINS] if test_plugins else []), *extra]:
            for node in _node_folders(folder.resolve()):
                entry = _register(node)

                # the second one would replace the first, in the registry or
                # in the archive, and the pipeline would run the wrong node
                if entry.keys() & registry.keys() or node.name in folders:
                    sys.exit(f'error: node {node} is already in the bundle')

                _add(zf, node, node.parent, EXTENSIONS)
                registry |= entry
                folders.add(node.name)

        if registry:
            entries = '\n'.join(
                f"    '{cls}': '{path}'," for cls, path in registry.items()
            )
            zf.writestr(
                f'{EXTENSIONS}/__init__.py', REGISTRY.format(entries=entries)
            )

    return target


def _node_folders(folder: pathlib.Path) -> list[pathlib.Path]:
    if not folder.is_dir():
        sys.exit(f'error: plugin folder not found: {folder}')

    return sorted(
        config.parent
        for config in folder.rglob('config.toml')
        if config.parent.name.startswith('_')
        and (config.parent / f'{config.parent.name[1:]}.py').is_file()
    )


def _register(node: pathlib.Path) -> dict[str, str]:
    module = node.name[1:]
    source = (node / f'{module}.py').read_text()
    found = re.search(r'^class (\w+)\(Node\b', source, re.MULTILINE)

    if found is None:
        sys.exit(f'error: no Node subclass in {node / (module + ".py")}')

    return {found.group(1): f'.{node.name}.{module}'}


def _add(
    zf: zipfile.ZipFile,
    folder: pathlib.Path,
    base: pathlib.Path,
    prefix: str,
):
    # rglob on a missing folder yields nothing: the bundle would build without
    # the nodes and fail only in the browser
    if not folder.is_dir():
        sys.exit(f'error: node folder not found: {folder}')

    for path in sorted(folder.rglob('*')):
        # assets.toml lists files for vendor.py, it is not part of the node
        if (
            path.suffix in PLUGIN_SUFFIXES
            and path.is_file()
            and path.name != 'assets.toml'
        ):
            zf.write(path, f'{prefix}/{path.relative_to(base)}')


def main():
    """Build dist/ from the command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.strip().split('\n')[0])
    parser.add_argument(
        '--juturna',
        type=pathlib.Path,
        default=os.environ.get('JUTURNA_REPO'),
        help='checkout of the juturna repository',
    )
    parser.add_argument(
        '--nodes',
        type=pathlib.Path,
        default=os.environ.get('JUTURNA_NODES_REPO'),
        help='checkout of the juturna-nodes repository',
    )
    parser.add_argument('--test-plugins', action='store_true')
    parser.add_argument(
        '--plugins',
        action='append',
        type=pathlib.Path,
        default=[],
        help='folder with extra nodes, each in a _<name> folder',
    )
    args = parser.parse_args()

    if args.juturna is None or not (args.juturna / 'pyproject.toml').is_file():
        parser.error(
            'pass --juturna (or set JUTURNA_REPO) to a juturna checkout'
        )

    if args.nodes is None or not (args.nodes / 'src/juturna/nodes').is_dir():
        parser.error(
            'pass --nodes (or set JUTURNA_NODES_REPO) to a juturna-nodes '
            'checkout'
        )

    shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir(parents=True)

    wheel = build_wheel(args.juturna)
    (DIST / 'wheel.txt').write_text(wheel.name)

    print(wheel.name)
    print(build_plugins(args.nodes, args.test_plugins, args.plugins).name)


if __name__ == '__main__':
    main()
