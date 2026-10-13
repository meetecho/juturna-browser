// Regression test for the bundle: bootstrap from dist/, then run a Pipeline
// (browser_input -> browser_output) fed with synthetic audio and one image.
import { bootstrapJuturna } from '../src/bootstrap.js';

const PYODIDE_VERSION = 'v314.0.6';
const say = (name, result) => self.postMessage({ type: 'step', name, result });
const errText = (e) => String((e && e.message) || e).split('\n').slice(-6).join(' | ');

self.onmessage = async () => {
  try {
    const { loadPyodide } = await import(`https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/pyodide.mjs`);
    const pyodide = await loadPyodide();
    const t0 = performance.now();
    await bootstrapJuturna(pyodide, { base: new URL('../dist/', import.meta.url) });
    say('bootstrap_ms', Math.round(performance.now() - t0));

    say('imports', String(await pyodide.runPythonAsync(`
import sys
import juturna
try:
    import importlib.metadata as md
    meta = 'metadata ' + md.version('juturna')
except Exception as e:
    meta = 'no metadata: ' + type(e).__name__
'juturna ' + juturna.__version__ + ' (' + meta + ') | heavy loaded: ' + ','.join(m for m in ('grpc','requests','av','websockets','micropip') if m in sys.modules)
`)));

    const cfg = { pipeline: { name: 'bd', id: 'bd-1', folder: '/tmp/juturna/bd', transport: 'browser',
      nodes: [{ name: 'in', type: 'BrowserInput', configuration: {} },
              { name: 'out', type: 'BrowserOutput', configuration: {} }],
      links: [{ from: 'in', to: 'out' }] } };
    self.juturna_config = JSON.stringify(cfg);
    const stopCell = new Int32Array(new SharedArrayBuffer(4));
    self.juturna_stop_cell = stopCell;

    await pyodide.runPythonAsync(`
import json
from js import Atomics, globalThis, postMessage, Object
from pyodide.ffi import run_sync, to_js
from juturna.components import Pipeline
pipe = Pipeline(json.loads(globalThis.juturna_config))
def feed(name, m): pipe._nodes[name].feed(m)
def run_pipeline():
    stop = globalThis.juturna_stop_cell
    pipe.warmup(); pipe.start()
    postMessage(to_js({'type': 'step', 'name': 'pipeline', 'result': 'running: ' + ','.join(pipe._nodes)}, dict_converter=Object.fromEntries))
    while not Atomics.load(stop, 0):
        r = Atomics.waitAsync(stop, 0, 0, 200)
        if r.async_: run_sync(r.value)
    pipe.stop()
    rep = {n: str(x.health) for n, x in pipe._nodes.items()}
    pipe.destroy()
    return rep
`);
    const feed = pyodide.globals.get('feed');
    const done = pyodide.globals.get('run_pipeline').callPromising();
    await new Promise((r) => setTimeout(r, 2500));
    for (let i = 0; i < 5; i++) {
      const audio = new Float32Array(1600).fill(0.1 * (i + 1));
      await feed.callPromising('in', { kind: 'audio', payload: { audio, sampling_rate: 16000, channels: 1, start: i * 0.1, end: (i + 1) * 0.1 }, meta: { i } });
    }
    const px = Uint8Array.from({ length: 48 }, (_, i) => i);
    await feed.callPromising('in', { kind: 'image', payload: { image: px, width: 4, height: 3, depth: 4, pixel_format: 'rgba', timestamp: 1 }, meta: { tag: 'img' } });
    await new Promise((r) => setTimeout(r, 1500));
    Atomics.store(stopCell, 0, 1); Atomics.notify(stopCell, 0);
    const rep = await done;
    say('report', JSON.stringify(rep.toJs({ dict_converter: Object.fromEntries })));
  } catch (e) { say('worker', 'FAIL: ' + errText(e)); }
  self.postMessage({ type: 'done' });
};
