# Contributing to `juturna-browser`

Thanks for your interest in contributing! Whether it's reporting a bug,
improving documentation, or submitting a pull request — you're welcome here.

## Code of Conduct

We expect everyone to be respectful and constructive. See our
[CODE OF CONDUCT](CODE_OF_CONDUCT.md) for further details.

## How to Contribute

1. **Fork the repository**
2. **Create a branch** for your changes:
   `git checkout -b feat/your-feature-name`
3. **Set up the checks**: see [Setup for Local Development](#setup-for-local-development)
4. **Write your code**: keep it clean, small, and focused.
5. **Run the test pages** that cover your change (see [Tests](#tests))
6. **Open a pull request**: include what you did, why, and which test pages
   you ran.

## PR Guidelines

* Keep PRs focused and minimal.
* Explain why you're making the change.
* Avoid unrelated changes in the same PR.
* If you're not sure, open an issue before coding.

## Code Style

The library is plain ES modules with no build step and no runtime
dependencies: no bundler, no npm package in `src/`. The rules are:

- **JavaScript**: 2-space indent, single quotes, semicolons, `===`, `const`
  by default, no trailing comma after the last element of a multi-line
  literal, 120 columns. Enforced by ESLint (`eslint.config.js`).
- **Python** (build scripts, nodes): the style of Juturna, 4-space indent,
  single quotes, 80 columns, Python 3.12. Enforced by Ruff (`ruff.toml`).
- A node module must import outside the browser: `js` and `pyodide.*` are
  imported inside the functions that use them. `build/check_nodes.py`
  checks it.

[docs/development.md](docs/development.md) describes how the code is laid
out, and [docs/write-a-node.md](docs/write-a-node.md) how to write a node.

## Setup for Local Development

You need Python 3.12 or later, Node 22 or later, and Chrome 137 or later.

```bash
npm ci                     # ESLint, for the JavaScript checks
pip install pre-commit
pre-commit install && pre-commit install --hook-type commit-msg
```

The two `pre-commit install` commands set up two hooks:

| Hook | When it runs | What it checks |
|------|--------------|----------------|
| `pre-commit` | before the commit message | merge markers, YAML/JSON syntax, trailing whitespace, final newline, private keys, Ruff, ESLint |
| `commit-msg` | after the commit message | the message follows Conventional Commits |

To run every check on every file:

```bash
pre-commit run --all-files
```

## Tests

The tests are HTML pages in `test/`, run in Chrome against a local server
that sends the COOP/COEP headers. Each page writes its outcome in
`window.__result`: every entry of `checks` is `'ok'` or `FAIL: ...`.

```bash
python3 build/build.py --juturna /path/to/juturna --nodes /path/to/juturna_nodes \
    --test-plugins
python3 serve.py 8765
# open http://localhost:8765/test/<page>.html
```

[docs/development.md](docs/development.md) lists the pages and the bundle
each one needs. After a change in `src/`, `build/` or a node, run at least
`facade`, `multi-worker`, `supervisor`, `restart`, `lifecycle`,
`ring-repair` and `large-frames`. After a change in a node, also run
`python build/check_nodes.py` with a Python that has Juturna and numpy.

## Commit Message Guidelines

Commits follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

- **type**: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`,
  `build`, `ci`, `chore`, `revert`
- **scope** (optional): the part of the code, e.g. `supervision`, `cache`,
  `examples`
- **subject**: imperative, lowercase, no period at the end

A breaking change takes a `!` after the type or scope
(`feat(api)!: rename feed options`), or a `BREAKING CHANGE:` footer.

The commit types also drive the changelog and the version of the next
release (release-please): `feat` bumps the minor version, `fix` the patch
version, and a breaking change the minor version until 1.0.

A maintainer runs the Release Please workflow by hand: it opens, or updates,
a pull request with the new version and changelog, and merging it creates the
tag and the GitHub release. To force a version, add a footer to a commit on
`main`:

```bash
git commit --allow-empty -m "chore: release 0.2.0" -m "Release-As: 0.2.0"
```

## CI Validation

Every pull request is checked by GitHub Actions:

1. **Commit Lint**: every commit message in the PR
2. **Ruff**: lint and format of the Python code
3. **ESLint**: lint of the JavaScript code
4. **Node Imports**: every node of `examples/` and `test/plugins` imports
   with Juturna 3.0.0

The test pages are not run by the CI: run them locally and say which ones
in the PR.

## Need Help?

Open an issue and describe what you're trying to do — we're usually friendly
and helpful.
