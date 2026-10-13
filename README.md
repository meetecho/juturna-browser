# juturna-browser

Run a [Juturna](https://github.com/meetecho/juturna) pipeline inside a browser
tab, from the same JSON configuration used on desktop.

`python3 serve.py` and open `index.html` for a demo-linking landing page with
the measured numbers.

The pipeline runs in a Pyodide Worker, or in several when nodes carry a
`"worker"` key. The page hands data to it with `feed()` and receives the
results with `on('message')`; capturing the data (microphone, files, canvas)
is up to the page.

```js
import { Juturna } from './src/juturna.js';

const config = { pipeline: { name: 'demo', id: 'demo-1', folder: '/tmp/juturna/demo',
  transport: 'browser',
  nodes: [{ name: 'in',  type: 'BrowserInput',  configuration: {} },
          { name: 'out', type: 'BrowserOutput', configuration: {} }],
  links: [{ from: 'in', to: 'out' }] }, plugins: ['plugins'] };

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

## Documentation

- [API reference](docs/api.md): every function, the configuration keys, the messages.
- [Guide](docs/guide.md): how it works, feeding audio and video, several Workers, lost
  Workers, writing a node.
- [Development](docs/development.md): build, run, tests, numbers.

## Requirements

- Chrome 137 or later (JSPI), tested on 151.
- Pyodide 314 or later, loaded from the CDN by the Worker.
- A page served with the `Cross-Origin-Opener-Policy: same-origin` and
  `Cross-Origin-Embedder-Policy: require-corp` headers (`SharedArrayBuffer`).
- Juturna 3.0.0 or later (it has the browser transport), and the nodes
  `BrowserInput` and `BrowserOutput` of juturna-nodes.

## Build

`dist/` holds a wheel of Juturna and the browser nodes, built from checkouts of
the `juturna` and `juturna-nodes` repositories:

```
python3 build/build.py --juturna /path/to/juturna --nodes /path/to/juturna_nodes
```

Run it again after any change in those checkouts. `JUTURNA_REPO` and
`JUTURNA_NODES_REPO` can replace `--juturna` and `--nodes`.

## Try it

```
python3 serve.py 8765
```

- <http://localhost:8765/examples/microphone.html>: microphone through the
  pipeline, plus an image round trip. Accept the microphone permission.
- The pages in `test/` check the bootstrap, the facade and the multi-Worker
  pipeline; they need `python3 build/build.py --test-plugins` first and write
  their outcome in `window.__result`.

`--plugins` is repeatable, so one build serves every demo from the same
`serve.py`:

```
python3 build/vendor.py examples/video-blur/plugins examples/noise-suppression/plugins examples/live-translation/plugins examples/plugins
python3 build/build.py --juturna /path/to/juturna --nodes /path/to/juturna_nodes \
    --plugins examples/video-blur/plugins \
    --plugins examples/noise-suppression/plugins \
    --plugins examples/live-translation/plugins \
    --plugins examples/plugins
```

## Background blur demo

Webcam frames go through a pipeline of three Workers: `person_mask` runs a
portrait segmentation model with onnxruntime-web and writes the mask in the
alpha channel, `background_blur` blurs what the mask marks as background
(numpy), and the result is drawn on a `<canvas>`.

```
python3 build/vendor.py examples/video-blur/plugins   # what person_mask declares in its assets.toml, into vendor/
python3 build/build.py --juturna /path/to/juturna --nodes /path/to/juturna_nodes \
    --plugins examples/video-blur/plugins
python3 serve.py 8765
```

Then open <http://localhost:8765/examples/video-blur/index.html>, which asks the
camera for 24 fps (`?fps=` changes it). The page keeps at most three frames in
flight (`?inflight=`) and drops the others, so the delay does not build up when
the pipeline is slower than the camera. With synthetic 640x480 frames at 24 fps
(`test/video-blur.html?fps=24&inflight=3`) the pipeline shows 24.6 fps with a
median delay of 64 ms, of which 20 ms of segmentation and 22 ms of blur; at 30
fps it shows 29.2 fps, dropping 6% of the frames. With the webcam at 24 fps
the page showed 24 fps with a median delay of 72 ms, 21 ms of segmentation and
26 ms of blur. Measured on a 12-core desktop.

<http://localhost:8765/examples/video-blur/canvas.html> is the same pipeline
minus `background_blur`: only `person_mask` runs, and the page's own canvas
does the compositing (`filter: blur()` for the background, `drawImage`
respecting the mask's own per-pixel alpha for the soft edge) instead of numpy
in a Worker. Same synthetic benchmark
(`test/video-blur-canvas.html?fps=24&inflight=3`): 0 frames dropped (2
before), median delay 40 ms (60 ms before), 8.8 ms of compositing against 22
ms of numpy blur it replaces - one Worker fewer, no accuracy tradeoff, same
segmentation.

## Live translation demo

English speech (or typed text) becomes a live transcript and a translation,
through two nodes on transformers.js/onnxruntime-web, each in its own Worker:
`whisper_asr` (Whisper, speech to English text) and `translate_opus`
(OPUS-MT/Marian, English to the target language — Italian, Spanish, Chinese
or German).

```
python3 build/vendor.py examples/live-translation/plugins examples/plugins
python3 build/build.py --juturna /path/to/juturna --nodes /path/to/juturna_nodes \
    --plugins examples/live-translation/plugins \
    --plugins examples/plugins
python3 serve.py 8765
```

- <http://localhost:8765/examples/live-translation/index.html>: microphone →
  `whisper_asr` → `translate_opus`. Target language, the transcription window
  and the microphone capture chunk are all set before pressing Start (changing
  the target language needs Stop, since it picks a different model).
- <http://localhost:8765/examples/live-translation/text.html>: a text box →
  `translate_opus` only, `whisper_asr` skipped. Typing feeds `browser_input`
  directly with an `object`-kind message (`{kind: 'object', payload: {text}}`
  — no framework change needed, `decode_message` already builds an
  `ObjectPayload` from it, the same shape `translate_opus` reads from
  `whisper_asr`'s own output). Debounced (500 ms default, configurable): the
  translation of the line being typed overwrites itself in place; Enter
  commits it to the history below and starts a new line.

Both nodes' `_LOAD` routes the vendored `models_url` through
transformers.js's **remote** branch (`env.allowRemoteModels = true`,
`env.remoteHost = modelsUrl`, pointed at our own server, not
`huggingface.co`), not its **local** one (`env.localModelPath`): a bug in
`@huggingface/transformers@4.3.0`'s tokenizer/processor existence pre-check
rejects any `localModelPath` that is an `http(s)` URL — the only form a
browser can use — so the local branch never loads `tokenizer.json`. A
model's Worker (first load) takes about 2.5 s; a 4 s window of
transcription and translation together, about 3 s, on the JFK sample also
used by `test/live-translation.html`.

## Messages

| `kind` | `payload` |
|---|---|
| `audio` | `audio` (`Float32Array`, or `Int16Array` normalised to [-1, 1]), `sampling_rate`, `channels`, `start`, `end` |
| `image` | `image` (flat `Uint8Array`), `width`, `height`, `depth`, `pixel_format`, `timestamp` |
| `bytes` | `cnt` (`Uint8Array`) |
| `object` | any JSON-compatible fields |

`meta` is free. `feed()` transfers the buffers of the payload (zero copy): they
detach in the caller unless `{copy: true}` is passed. Sampling rate, chunking
and timestamps are the producer's business: they travel in the messages.
`pipe.input(name).port()` returns a `MessagePort` to hand to an
`AudioWorklet` or another Worker, so that data reaches the pipeline without
going through the page.

## Several Workers

A node runs in the Worker named by its optional `"worker"` key (`main` by
default). Nodes of different Workers are linked as any other; the messages
travel through shared memory. A node that keeps the CPU busy in its own
Worker no longer stalls the others.
