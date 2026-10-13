// Installs Juturna into a Pyodide instance from the artifacts of build.py: the
// wheel and plugins.zip are unpacked, no package manager involved. There is
// one wheel and nothing to resolve (av, requests and grpc have no Pyodide build
// and Juturna does not import them), so micropip would only add its own load
// time and, for websockets, a download from PyPI in every Worker.
//
// Fetching does not need Pyodide: fetchAssets() can start before loadPyodide()
// and run while it loads. Files are fetched with cache:'no-store', so a rebuilt
// bundle is never served from a stale HTTP cache.

/** Fetch the wheel and the plugins archive of `base`. */
export async function fetchAssets(base) {
  const get = async (name) => {
    const resp = await fetch(new URL(name, base), { cache: 'no-store' });
    if (!resp.ok) throw new Error(`failed to fetch ${name}: HTTP ${resp.status}`);
    return resp;
  };
  const bytes = async (response) => new Uint8Array(await (await response).arrayBuffer());

  const [wheel, plugins] = await Promise.all([
    get('wheel.txt').then((resp) => resp.text()).then((name) => get(name.trim())).then(bytes),
    get('plugins.zip').then(bytes),
  ]);
  return { wheel, plugins };
}

/**
 * Install Juturna and its plugins in `pyodide`.
 * @param {object} pyodide a loaded Pyodide instance
 * @param {{base: URL, assets?: Promise}} options `assets` is the promise of
 *   `fetchAssets(base)`, if it was started before Pyodide finished loading.
 */
export async function bootstrapJuturna(pyodide, { base, assets = fetchAssets(base) }) {
  await pyodide.loadPackage('numpy');

  const { wheel, plugins } = await assets;
  pyodide.unpackArchive(wheel, 'wheel');
  // the nodes are subpackages of juturna (juturna.nodes, juturna.extensions):
  // they go next to the library
  const site = pyodide.runPython("import sysconfig; sysconfig.get_paths()['purelib']");
  pyodide.unpackArchive(plugins, 'zip', { extractDir: site });
}
