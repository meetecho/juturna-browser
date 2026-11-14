# juturna-browser

juturna-browser runs a [Juturna](https://github.com/meetecho/juturna) pipeline
inside a browser tab, from the same JSON configuration used on a server. The
nodes run in Pyodide Web Workers; the page feeds them with `feed()` and
receives their results with `on('message')`. Audio and video from the
microphone and the camera are processed where they are captured: no server
receives them.

```js
import { Juturna } from './src/juturna.js';

const config = { pipeline: { name: 'demo', id: 'demo-1', folder: '/tmp/juturna/demo',
  transport: 'browser',
  nodes: [{ name: 'in',  type: 'BrowserInput',  configuration: {} },
          { name: 'out', type: 'BrowserOutput', configuration: {} }],
  links: [{ from: 'in', to: 'out' }] } };

const jt   = await Juturna.create();
const pipe = await jt.pipeline(config);
pipe.output('out').on('message', ({ kind, payload, meta }) => render(payload));
pipe.onError((error) => console.error(error));
const input = pipe.input('in');

await pipe.start();
input.feed({ kind: 'audio', payload: { audio: float32Chunk, sampling_rate: 16000 } });
await pipe.stop();
await pipe.destroy();
jt.terminate();
```

`BrowserInput` and `BrowserOutput` are the two ends of the pipeline; the nodes
that do the work go between them, each in the Worker its `"worker"` key names.
Capturing the data (microphone, files, canvas) is up to the page.

## When it fits

- The data is in the page and should stay there: speech recognition,
  translation, segmentation or denoising on the user's own device.
- The same pipeline has to run on a server and in a browser, with one
  configuration and the same nodes.
- A node needs its own thread: a node that keeps the CPU busy only stalls its
  own Worker.

Nodes run in Pyodide: numpy is available, most packages with native code are
not. A node can call JavaScript, so onnxruntime-web, transformers.js and
WebAssembly builds of native libraries are the way to run models.

## Requirements

- Chrome 137 or later (JSPI), tested on 151.
- Pyodide 314 or later, loaded from the CDN by the Worker.
- A page served with the `Cross-Origin-Opener-Policy: same-origin` and
  `Cross-Origin-Embedder-Policy: require-corp` headers, without which
  `SharedArrayBuffer` does not exist. `serve.py` sends them.
- Juturna 3.0.0 or later (it has the browser transport), and the nodes
  `BrowserInput` and `BrowserOutput` of juturna-nodes.

## Documentation

| Page | Read it to |
|---|---|
| [Guide](docs/guide.md) | Build and run a first pipeline, then feed audio and video, use several Workers, handle lost Workers, write a node |
| [How it works](docs/how-it-works.md) | Understand the Workers, the shared-memory queues and what each step costs |
| [Demos](docs/demos.md) | Try the six demo pages, see what each one measures, and find the licenses of the models |
| [API reference](docs/api.md) | Look up a function, a configuration key, a message format or where an error shows |
| [Development](docs/development.md) | Build the bundle, fetch third-party files, run the test pages |

## License

MIT, see [LICENSE](LICENSE). The models used by the demos have their own
licenses, listed in [Demos](docs/demos.md#models-and-licenses).
