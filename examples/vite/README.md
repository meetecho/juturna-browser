# juturna-browser in a Vite app

A page that runs a `BrowserInput` → `BrowserOutput` pipeline, using the
juturna-browser npm package as an app would. The package is the tarball of
`npm pack` of this repository, not a link to it, so the app sees only the
published files.

Needs Node, python3 3.11 or later with pip, and Chrome 137 or later.

```
cd examples/vite
npm run setup       # installs vite, packs and installs the package, builds public/juturna from PyPI
npm run dev         # http://localhost:5173/
npm run build && npm run preview    # http://localhost:4173/
```

The page shows `window.__result`: `{ checks: { round_trip: 'ok' } }` when the
message fed to `in` comes back from `out`, `fatal` with the exception if the
page failed. Run `npm run setup` again after a change in `src/` or `build/`.
