# juturna-browser as a standalone folder

A static page that runs a `BrowserInput` → `BrowserOutput` pipeline from the
folder `juturna-browser build --out` writes, using the npm package as a user
would. The package is the tarball of `npm pack` of this repository, not a link
to it, so the example sees only the published files.

Needs Node, python3 3.12 or later with pip, and Chrome 137 or later.

```
cd examples/standalone
npm run setup        # packs and installs the package, builds juturna/ from PyPI
cd ../..
python3 serve.py 8765
```

Open <http://127.0.0.1:8765/examples/standalone/index.html>. The page shows
`window.__result`: `{ checks: { round_trip: 'ok' } }` when the message fed to
`in` comes back from `out`, `fatal` with the exception if the page failed. Run
`npm run setup` again after a change in `src/` or `build/`.
