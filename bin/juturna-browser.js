#!/usr/bin/env node
// Runs the scripts of build/ with python3: build (the bundle), vendor (the
// third-party files of the nodes), check (imports the nodes with CPython).

import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const SCRIPTS = { build: 'build.py', vendor: 'vendor.py', check: 'check_nodes.py' };
const [command, ...args] = process.argv.slice(2);

if (!SCRIPTS[command]) {
  console.error('usage: juturna-browser <build|vendor|check> [options]\n'
    + '  run a command with --help for its options');
  process.exit(2);
}

// in a checkout check defaults to examples/ and test/plugins; in node_modules
// those folders are the package's own, so the folders must be given
if (command === 'check' && args.length === 0) {
  console.error('usage: juturna-browser check FOLDER [FOLDER ...]\n'
    + '  imports the nodes under each FOLDER with CPython: needs Python 3.12 or later, '
    + 'with juturna and numpy installed');
  process.exit(2);
}

// build downloads the wheels with pip; vendor needs only the standard library,
// check reports a missing juturna by itself
const needsPip = command === 'build';
const probe = spawnSync('python3', ['-c', 'import sys, importlib.util; sys.exit(sys.version_info < (3, 11)'
  + (needsPip ? ' or importlib.util.find_spec("pip") is None)' : ')')]);
if (probe.status !== 0) {
  console.error(`juturna-browser needs python3 3.11 or later${needsPip ? ', with pip,' : ''} on the PATH: `
    + 'install it from https://www.python.org/downloads/ or with your package manager (python3 and python3-pip)');
  process.exit(1);
}

const script = fileURLToPath(new URL(`../build/${SCRIPTS[command]}`, import.meta.url));
const run = spawnSync('python3', [script, ...args], { stdio: 'inherit' });
if (run.error) throw run.error;
process.exit(run.status ?? 1);
