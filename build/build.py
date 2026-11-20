#!/usr/bin/env python3
r"""
Build what a Pyodide Worker needs to run Juturna: a wheel of the library and
a zip with the browser nodes.

Usage:
    python3 build/build.py [--juturna /path/to/juturna] \\
        [--nodes /path/to/juturna_nodes] [--test-plugins] [--plugins DIR ...] \\
        [--out DIR]

``--juturna`` defaults to the ``JUTURNA_REPO`` environment variable, ``--nodes``
to ``JUTURNA_NODES_REPO``. Without a checkout, the wheel of the pinned release
(``JUTURNA_VERSION``, ``NODES_VERSION``) is downloaded from PyPI with pip.

Output, in ``dist/`` of this repository or, with ``--out DIR``, in
``DIR/dist/`` next to ``DIR/src/`` with the JavaScript of ``src/``: a folder
with the whole runtime, to serve as static files
(``import { Juturna } from '<DIR url>/src/juturna.js'``):
    juturna-<version>-py3-none-any.whl   the library, built as it is in the
                                         checkout (uncommitted changes included)
                                         or downloaded from PyPI
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
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
SRC = ROOT / 'src'

# PY_RUNTIME uses Juturna internals: the JS of this package and the wheel must
# match, so the releases fetched from PyPI are fixed here, with the sha256 of
# their py3-none-any wheel (the digests PyPI lists for the release)
JUTURNA_VERSION = '3.0.0'
JUTURNA_SHA256 = (
    '786d80cf7b8e98d5c6d51f5186af11419793a53895f199caa4bbda29bd56b14e'
)
NODES_VERSION = '0.1.1'
NODES_SHA256 = (
    '9b610166b2a5a954296304e84a618875a14ba03e4abc993f454ca555820318c2'
)
PYPI_INDEX = 'https://pypi.org/simple'

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


def build_wheel(juturna: pathlib.Path, out: pathlib.Path) -> pathlib.Path:
    """Build the wheel of the juturna checkout into out."""
    subprocess.run(
        [
            sys.executable,
            '-m',
            'pip',
            'wheel',
            '--no-deps',
            '-q',
            '-w',
            str(out),
            str(juturna),
        ],
        check=True,
    )

    return next(out.glob('juturna-*.whl'))


def download_wheel(
    name: str, version: str, sha256: str, out: pathlib.Path
) -> pathlib.Path:
    """Download the wheel of a PyPI release into out and check its sha256."""
    # the wheel runs in Pyodide, not in this interpreter: its Requires-Python
    # does not apply here; --index-url keeps a user's extra-index-url out
    subprocess.run(
        [
            sys.executable,
            '-m',
            'pip',
            'download',
            f'{name}=={version}',
            '--no-deps',
            '--only-binary=:all:',
            '--ignore-requires-python',
            '--disable-pip-version-check',
            '--index-url',
            PYPI_INDEX,
            '-q',
            '-d',
            str(out),
        ],
        check=True,
    )

    wheel = out / f'{name.replace("-", "_")}-{version}-py3-none-any.whl'
    if not wheel.is_file():
        sys.exit(f'error: pip did not download {wheel.name} into {out}')

    with wheel.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()

    if digest != sha256:
        wheel.unlink()
        sys.exit(
            f'error: sha256 mismatch for {wheel.name}: expected {sha256}, '
            f'got {digest}'
        )

    return wheel


def extract_nodes(tmp: pathlib.Path) -> pathlib.Path:
    """Extract juturna/nodes of the pinned juturna-nodes wheel into tmp."""
    wheel = download_wheel('juturna-nodes', NODES_VERSION, NODES_SHA256, tmp)

    with zipfile.ZipFile(wheel) as zf:
        zf.extractall(
            tmp, [n for n in zf.namelist() if n.startswith('juturna/nodes/')]
        )

    return tmp / 'juturna' / 'nodes'


def build_plugins(
    package: pathlib.Path,
    test_plugins: bool,
    extra: list[pathlib.Path],
    out: pathlib.Path,
) -> pathlib.Path:
    """Zip package (juturna/nodes) and the extra plugins into plugins.zip."""
    target = out / 'plugins.zip'
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


def copy_runtime(target: pathlib.Path):
    """Copy the modules of src/ into target."""
    target.mkdir(parents=True, exist_ok=True)
    for path in SRC.glob('*.js'):
        shutil.copyfile(path, target / path.name)


def main():
    """Build the bundle from the command line arguments."""
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
    parser.add_argument(
        '--test-plugins',
        action='store_true',
        help='add the nodes of test/plugins (only in a checkout of this '
        'repository)',
    )
    parser.add_argument(
        '--plugins',
        action='append',
        type=pathlib.Path,
        default=[],
        help='folder with extra nodes, each in a _<name> folder',
    )
    parser.add_argument(
        '--out',
        type=pathlib.Path,
        help='standalone output folder: DIR/src with the JavaScript, DIR/dist '
        'with the bundle (default: only the bundle, in dist/ of this '
        'repository)',
    )
    args = parser.parse_args()

    if args.juturna and not (args.juturna / 'pyproject.toml').is_file():
        parser.error(f'not a juturna checkout: {args.juturna}')

    if args.nodes and not (args.nodes / 'src/juturna/nodes').is_dir():
        parser.error(f'not a juturna-nodes checkout: {args.nodes}')

    # src/ next to dist/ keeps the default base of juturna.js (../dist/)
    site = args.out
    if site:
        if (site / 'src').resolve() == SRC:
            parser.error(f'--out would overwrite {SRC}: choose another folder')

        args.out = site / 'dist'
    else:
        args.out = DIST

    # out may be a folder of the site: only our files are removed, and an old
    # wheel must go or the glob below could pick it; wheel.txt goes too, so a
    # failed build does not leave it naming a missing wheel
    args.out.mkdir(parents=True, exist_ok=True)
    for old in [*args.out.glob('juturna-*.whl'), args.out / 'wheel.txt']:
        old.unlink(missing_ok=True)

    if args.juturna:
        print(f'juturna: checkout {args.juturna.resolve()}')
        wheel = build_wheel(args.juturna, args.out)
    else:
        print(f'juturna: {JUTURNA_VERSION} from PyPI')
        wheel = download_wheel(
            'juturna', JUTURNA_VERSION, JUTURNA_SHA256, args.out
        )
    (args.out / 'wheel.txt').write_text(wheel.name)
    print(wheel.name)

    with tempfile.TemporaryDirectory() as tmp:
        if args.nodes:
            print(f'juturna-nodes: checkout {args.nodes.resolve()}')
            package = args.nodes / 'src' / 'juturna' / 'nodes'
        else:
            print(f'juturna-nodes: {NODES_VERSION} from PyPI')
            package = extract_nodes(pathlib.Path(tmp))

        plugins = build_plugins(
            package, args.test_plugins, args.plugins, args.out
        )
    print(plugins.name)

    # last, so a failed build does not leave new modules next to an old bundle
    if site:
        copy_runtime(site / 'src')


if __name__ == '__main__':
    main()
