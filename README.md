# juturna-browser

[![npm](https://img.shields.io/npm/v/juturna-browser)](https://www.npmjs.com/package/juturna-browser)

juturna-browser runs a [Juturna](https://github.com/meetecho/juturna) pipeline
inside a browser tab. It uses the same JSON configuration format and node
model as a server, but with nodes written for Pyodide, not the ones a server
runs: `"transport": "browser"` in the pipeline, and the `BrowserInput` and
`BrowserOutput` nodes at the boundary with the page. The nodes run in
Pyodide Web Workers; the page feeds them with `feed()` and receives their
results with `on('message')`. Audio and video from the microphone and the
camera are processed where they are captured: no server receives them.

Try the [hosted demos](https://meetecho.github.io/juturna/browser/demos.html),
or read the [Juturna documentation](https://meetecho.github.io/juturna/).

## Install

```
npm install juturna-browser
npx juturna-browser build --out static/juturna
```

The package holds the JavaScript runtime and the build scripts, not a bundle:
`juturna-browser build --out` writes a standalone folder with the whole
runtime: `src/` with the JavaScript of the package and `dist/` with the wheel
of Juturna 3.0.0 and the browser nodes of juturna-nodes 0.1.1, both downloaded
from PyPI, plus the nodes of your own `--plugins` folders. It needs python3
3.12 or later with pip; Juturna does not have to be installed (only
`juturna-browser check` needs it). Serve the folder as static files, with the
isolation headers, and import it from the page (here `static/` is the root of
the site):

```js
import { Juturna } from '/juturna/src/juturna.js';

const config = { pipeline: { name: 'demo', id: 'demo-1', folder: '/tmp/juturna/demo',
  transport: 'browser',
  nodes: [{ name: 'in',  type: 'BrowserInput',  configuration: {} },
          { name: 'out', type: 'BrowserOutput', configuration: {} }],
  links: [{ from: 'in', to: 'out' }] } };

const jt   = await Juturna.create();
const pipe = await jt.pipeline(config);
// render: whatever the page does with a result
pipe.output('out').on('message', ({ kind, payload, meta }) => render(payload));
pipe.onError((error) => console.error(error));
const input = pipe.input('in');

await pipe.start();
// float32Chunk: a Float32Array of 16 kHz samples, from the microphone or a file
input.feed({ kind: 'audio', payload: { audio: float32Chunk, sampling_rate: 16000 } });
await pipe.stop();
await pipe.destroy();
jt.terminate();
```

`BrowserInput` and `BrowserOutput` are the two ends of the pipeline; the nodes
that do the work go between them, each in the Worker its `"worker"` key names.
Capturing the data (microphone, files, canvas) is up to the page.

[Use the npm package](docs/guide.md#use-the-npm-package) covers the headers and
the builders, and [examples/standalone](examples/standalone) is a working page.

## Quick start from a checkout

```
git clone https://github.com/meetecho/juturna-browser
git clone --branch juturna-v3.0.0 https://github.com/meetecho/juturna
git clone --branch juturna-nodes-v0.1.1 https://github.com/meetecho/juturna_nodes
cd juturna-browser
python3 build/build.py --juturna ../juturna --nodes ../juturna_nodes
python3 serve.py 8765
```

Open <http://127.0.0.1:8765/examples/microphone.html> in Chrome and press
Start. The microphone demo needs nothing more; the demos that run models also
need the files fetched by `build/vendor.py` and their `--plugins` folders, as
[Run them locally](docs/demos.md#run-them-locally) shows. To write a page of
your own, follow the [Guide](docs/guide.md).

A page of the checkout imports `src/` and uses the `dist/` bundle.

## When it fits

- The data is in the page and should stay there: speech recognition,
  translation, segmentation or denoising on the user's own device.
- You want to keep the same pipeline structure and configuration format on a
  server and in a browser, with a browser version of each node.
- A node needs its own thread: a node that keeps the CPU busy only stalls its
  own Worker.

Nodes run in Pyodide: numpy is available, most packages with native code are
not. A node can call JavaScript, so onnxruntime-web, transformers.js and
WebAssembly builds of native libraries are the way to run models.

## Requirements

- Chrome 137 or later (JSPI), tested on 157. Other browsers are not
  supported.
- python3 3.12 or later with pip, to run `juturna-browser build`.
- Pyodide, loaded from the jsDelivr CDN by the Worker: v314.0.6 by default,
  another release with the `pyodide` option of `Juturna.create()`.
- A page served with the `Cross-Origin-Opener-Policy: same-origin` and
  `Cross-Origin-Embedder-Policy: require-corp` headers, without which
  `SharedArrayBuffer` does not exist. `serve.py` sends them.
- Juturna 3.0.0 (it has the browser transport), and the nodes `BrowserInput`
  and `BrowserOutput` of juturna-nodes 0.1.1: the worker code uses Juturna
  internals, so `juturna-browser build` fetches exactly these releases unless
  `--juturna` and `--nodes` point to checkouts.

## Documentation

| Page | Read it to |
|---|---|
| [Guide](docs/guide.md) | Build and run a first pipeline, then feed audio and video, use several Workers, handle lost Workers |
| [Write a browser node](docs/write-a-node.md) | Write a node, build it into the bundle and run it in a page |
| [How it works](docs/how-it-works.md) | Understand the Workers, the shared-memory queues and what each step costs |
| [Demos](docs/demos.md) | Try the six demos and find the licenses of the models |
| [API reference](docs/api.md) | Look up a function, a configuration key, a message format or where an error shows |
| [Development](docs/development.md) | Build the bundle, fetch third-party files, run the test pages |
| [Contributing](CONTRIBUTING.md) | Report a bug, propose a change or open a pull request |
| [Security](SECURITY.md) | Report a vulnerability |

## License

MIT, see [LICENSE](LICENSE). The models used by the demos have their own
licenses, listed in [Demos](docs/demos.md#models-and-licenses).
