#!/usr/bin/env python3
"""Fetch the third-party files that nodes load at run time into vendor/.

A node that needs such files (a model, a JavaScript runtime) declares them in
an ``assets.toml`` next to its code:

    [[asset]]
    url = "https://..."
    path = "person_mask/selfie.onnx"   # relative to vendor/
    sha256 = "..."
    license = "Apache-2.0"

Where the files live is decided by the page that uses the node (the node only
gets URLs in its configuration), and vendor/ is where the examples put them:
served by serve.py, with its cross-origin isolation headers, because a page
with ``Cross-Origin-Embedder-Policy: require-corp`` cannot load them from a host
that does not allow it.

Usage:
    python3 build/vendor.py SOURCE [SOURCE ...] [--dest DIR] [--force]

A SOURCE is one of:
- an ``assets.toml`` file;
- a folder of plugins (or any folder): every ``assets.toml`` under it is used;
- a pipeline configuration (``*.json``): the ``assets.toml`` of the
  ``extensions.nodes.*`` nodes it uses, looked up in the folders given with
  ``--plugins``.

A file that is there and has the right checksum is not fetched again. One with
a different checksum is an error, unless ``--force`` replaces it.
"""

import argparse
import hashlib
import json
import pathlib
import re
import sys
import tomllib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = 'assets.toml'


def load_manifest(path: pathlib.Path) -> list[dict]:
    with path.open('rb') as f:
        assets = tomllib.load(f).get('asset', [])

    for asset in assets:
        missing = {'url', 'path', 'sha256'} - set(asset)

        if missing:
            raise SystemExit(f'{path}: an asset lacks {sorted(missing)}')

        asset['manifest'] = path

    return assets


def _node_class(node: pathlib.Path) -> str | None:
    source = node / f'{node.name[1:]}.py'

    if not node.name.startswith('_') or not source.is_file():
        return None

    found = re.search(r'^class (\w+)\(Node\b', source.read_text(), re.M)

    return found and found.group(1)


def find_node_manifests(
    pipeline: pathlib.Path, plugins: list[pathlib.Path]
) -> list[pathlib.Path]:
    config = json.loads(pipeline.read_text())
    nodes = {
        node: _node_class(node)
        for folder in plugins
        for node in folder.rglob('_*')
        if node.is_dir()
    }
    found = []

    for node in config['pipeline']['nodes']:
        # extensions.nodes.MyNode -> MyNode
        name = node['type'].rsplit('.', 1)[-1]
        folders = [path for path, cls in nodes.items() if cls == name]

        if folders:
            if (folders[0] / MANIFEST).is_file():
                found.append(folders[0] / MANIFEST)
        elif node['type'].startswith('extensions.'):
            print(f'warning: node {node["name"]} ({name}) not found in {plugins}')

    return found


def collect(
    sources: list[pathlib.Path], extra_plugins: list[pathlib.Path]
) -> list[dict]:
    manifests = []

    for source in sources:
        if source.is_dir():
            manifests += sorted(source.rglob(MANIFEST))
        elif source.suffix == '.json':
            manifests += find_node_manifests(source, extra_plugins)
        else:
            manifests.append(source)

    assets, seen = [], {}

    for manifest in dict.fromkeys(manifests):
        for asset in load_manifest(manifest):
            other = seen.get(asset['path'])

            if other is None:
                seen[asset['path']] = asset
                assets.append(asset)
            elif (other['url'], other['sha256']) != (
                asset['url'],
                asset['sha256'],
            ):
                raise SystemExit(
                    f'{asset["path"]} is declared with different contents by '
                    f'{other["manifest"]} and {manifest}'
                )

    return assets


def sha256_of(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(asset: dict, dest: pathlib.Path, force: bool) -> str:
    target = dest / asset['path']

    if not target.resolve().is_relative_to(dest.resolve()):
        raise SystemExit(
            f'{asset["path"]} in {asset["manifest"]} is outside {dest}'
        )

    if target.exists():
        if sha256_of(target) == asset['sha256']:
            return 'already there'

        if not force:
            raise SystemExit(
                f'{target} exists with a different checksum: it is not what '
                f'{asset["manifest"]} declares (--force replaces it)'
            )

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.part')
    urllib.request.urlretrieve(asset['url'], temporary)  # noqa: S310

    if sha256_of(temporary) != asset['sha256']:
        temporary.unlink()
        raise SystemExit(
            f'{asset["url"]} does not have the checksum declared in '
            f'{asset["manifest"]}'
        )

    temporary.replace(target)

    return f'{target.stat().st_size} bytes'


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('sources', nargs='+', type=pathlib.Path)
    parser.add_argument('--dest', type=pathlib.Path, default=ROOT / 'vendor')
    parser.add_argument(
        '--plugins',
        action='append',
        type=pathlib.Path,
        default=[],
        help='folder of nodes to look into for a pipeline configuration',
    )
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()

    assets = collect(args.sources, args.plugins)

    if not assets:
        print('no assets declared')
        return

    for asset in assets:
        state = fetch(asset, args.dest, args.force)
        print(f'{asset["path"]}: {state} ({asset.get("license", "no license")})')


if __name__ == '__main__':
    sys.exit(main())
