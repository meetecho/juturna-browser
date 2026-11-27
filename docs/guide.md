# Guide

This guide builds a first pipeline in a page, then covers the tasks that come
next: feeding audio, video and text, spreading nodes over several Workers, handling
a Worker that is lost and watching the messages. Writing a node has its own
page, [Write a browser node](write-a-node.md). How the pieces work underneath
is in [How it works](how-it-works.md); every function is in the
[API reference](api.md).

## Your first pipeline

**1. Build the bundle.** `dist/` holds a wheel of Juturna and the browser
nodes, built from checkouts of the `juturna` (3.0.0) and `juturna-nodes` (0.1.1)
repositories:

```
python3 build/build.py --juturna /path/to/juturna --nodes /path/to/juturna_nodes
```

Run it again after any change in those checkouts. `JUTURNA_REPO` and
`JUTURNA_NODES_REPO` can replace `--juturna` and `--nodes`.

**2. Serve the folder.** `serve.py` sends the isolation headers that
`SharedArrayBuffer` needs:

```
python3 serve.py 8765
```

**3. Write the page.** A module script imports the API from `src/`, builds
the pipeline, feeds it and listens to its output:

```js
import { Juturna } from './src/juturna.js';

const config = { pipeline: { name: 'demo', id: 'demo-1', folder: '/tmp/juturna/demo',
  transport: 'browser',
  nodes: [{ name: 'in',  type: 'BrowserInput',  configuration: {} },
          { name: 'out', type: 'BrowserOutput', configuration: {} }],
  links: [{ from: 'in', to: 'out' }] } };

const jt   = await Juturna.create();
const pipe = await jt.pipeline(config);
pipe.output('out').on('message', ({ kind, payload, meta }) => console.log(kind, meta));
pipe.onError((error) => console.error(error));
const input = pipe.input('in');

await pipe.start();
input.feed({ kind: 'audio', payload: { audio: new Float32Array(1600), sampling_rate: 16000 }, meta: { i: 0 } });
await pipe.stop();
await pipe.destroy();
jt.terminate();
```

`BrowserInput` and `BrowserOutput` are the two ends of the pipeline: what
the page feeds and what it receives. Between them go the nodes that do the
work. `Juturna.create()` takes about 3 to 4 seconds: it loads Pyodide and
installs Juturna in every Worker.

<a class="try-it" href="../examples/microphone.html">▶ Try it</a>

`examples/microphone.html` is the same pipeline fed by
the microphone, plus an image round trip. Accept the microphone permission.

## Use the npm package

Installed from npm, the package gives a `juturna-browser` command that runs the
scripts of `build/` with python3 3.12 or later (with pip for `build`). Build a
standalone folder with the whole runtime, and fetch the third-party files of
your nodes if they declare any, into the folder your server serves:

```
npm install juturna-browser
npx juturna-browser build --plugins ./nodes --out static/juturna
npx juturna-browser vendor ./nodes --dest static/vendor
```

`static/juturna` gets `src/`, the JavaScript of the package, and `dist/`, the
bundle. Without `--juturna` and `--nodes`, `build` downloads the wheels of
Juturna 3.0.0 and juturna-nodes 0.1.1 from PyPI: the versions the JavaScript of
the package is written for. Run it again after changing a node or upgrading the
package. Only the files the build writes are replaced (the modules in `src/`; the
wheel, `wheel.txt` and `plugins.zip` in `dist/`); the rest of the folder is
left as it is. Outside a checkout, give `vendor` a `--dest`: its default,
`vendor/` of the package, would be inside `node_modules`. The nodes then load
those files from the URLs their configuration gives.

Serve the folder as static files and import it from the page. With `static/`
served at the root of the site:

```js
import { Juturna } from '/juturna/src/juturna.js';

const jt = await Juturna.create();
```

`src/` finds the bundle in `../dist/` by itself, so the page passes no `base`.
Every server that serves the page, production included, must send the two
headers that make `SharedArrayBuffer` available:

```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

and the files the page loads from elsewhere must be served from the same
site (`static/vendor` above), not from another host.

With a bundler, copy the folder among the static assets the bundler serves and
publishes as they are, and import `src/juturna.js` at run time by its URL: keep
it out of the bundle, since the Worker and the bundle are found relative to
`src/juturna.js`.

`juturna-browser check ./nodes` imports your nodes with CPython, as
[Write a browser node](write-a-node.md) explains; unlike `build`, it needs
juturna and numpy installed, and a CPython of the same minor version as Pyodide
gives it the most faithful result. [examples/standalone](../examples/standalone)
is a working page.

## Feed audio from the microphone

The page captures the audio; `examples/microphone.html` is a complete example.
Capturing in an `AudioWorklet` and posting to a `port()` keeps the main thread
out of the way:

```js
const port = input.port();                                   // a MessagePort
workletNode.port.postMessage({ port }, [port]);              // hand it to the worklet
// in the worklet: port.postMessage({ kind: 'audio', payload: { audio, sampling_rate: 16000 } }, [audio.buffer]);
```

Sampling rate, chunking and timestamps travel in the messages: nothing in the
nodes is configured about the page.

A node reads its configuration when it warms up. To change a value, such as
the attenuation of `denoise_dfn`, build a new pipeline:
`examples/noise-suppression` does it to process the audio it already recorded
again.

## Feed video and drop frames

A frame is an `image` message. `examples/video-blur` reads the camera with a
`<video>` and a canvas, and feeds `getImageData()` at 24 fps:

```js
input.feed({ kind: 'image', payload: { image: new Uint8Array(data.buffer), width: 640, height: 480,
                                       depth: 4, pixel_format: 'rgba', timestamp: n }, meta: { t: performance.now() } });
```

Real-time video needs the page to decide what happens when the pipeline is
slower than the camera: `feed()` does not push back, the frames pile up and so
does the delay. The demo counts the frames in flight (fed and not yet shown)
and drops the new ones beyond three.

The demo runs `person_mask`, a portrait segmentation model on
onnxruntime-web that writes the mask in the alpha channel, then
`background_blur`, which blurs what the mask marks as background with numpy.
`canvas.html` drops `background_blur` and composites on the page's own canvas:
`filter: blur()` for the background, and `drawImage` respecting the per-pixel
alpha of the mask for the soft edge. That saves a Worker and loses nothing,
since the segmentation is the same.

## Feed text and objects

Text and other plain values travel as an `object` message (the other kinds are
`audio`, `image` and `bytes`): `decode_message` builds an `ObjectPayload` from
its fields. `examples/live-translation/text.html` feeds the text of a box to
`translate_opus` alone, in the same shape `translate_opus` reads from
`whisper_asr`:

```js
input.feed({ kind: 'object', payload: { text }, meta: { final } });
```

## Run nodes in several Workers

Give a node a `"worker"` and it runs there; without the key it runs in
`main`:

```js
nodes: [
  { name: 'in',   type: 'BrowserInput',   configuration: {} },
  { name: 'mask', type: 'extensions.nodes.PersonMask',     worker: 'ml',  configuration: { /* ... */ } },
  { name: 'blur', type: 'extensions.nodes.BackgroundBlur', worker: 'cpu', configuration: {} },
  { name: 'out',  type: 'BrowserOutput',  configuration: {} },
]
```

A Worker is one thread with one Pyodide. A node that keeps the CPU busy holds
up every other node of its Worker, so it belongs in a Worker of its own. Each Worker costs memory (a Pyodide instance) and its start,
which happens in parallel with the others.

The demos give each heavy node a Worker of its own: `person_mask` and
`background_blur` in `examples/video-blur`, `whisper_asr` (Whisper on
transformers.js) and `translate_opus` (OPUS-MT) in
`examples/live-translation`. The Kroko demos run `transcriber_kroko_wasm`,
Kroko's streaming Zipformer compiled to WebAssembly with sherpa-onnx; that
build is single-threaded, so `?maxThreads=` on the translation page applies to
`translate_opus` only.

## Lost Workers

A Worker can be lost: the browser kills it (out of memory), it fails with an
uncaught error, or it stops answering. The page notices in two ways: the error
event of the Worker, and a ping every `pingMs` that must be answered within
`timeoutMs`.

When a Worker is lost:

1. it is terminated, and calls waiting for it fail;
2. the queues that lead to its nodes are closed, so the nodes of other Workers
   that write to them are not left waiting for room: their messages are
   dropped, and the node logs a warning once;
3. `pipe.onWorkerLost({worker, reason, willRestart})` and `pipe.onError` fire,
   and `status()` shows the Worker as `lost`;
4. the queues it was writing to are repaired (see
   [How it works](how-it-works.md#a-worker-lost-in-the-middle-of-a-write)).

The rest of the pipeline keeps running, and `stop()` and `destroy()` work on
it. By default nothing restarts on its own and no state is recovered: what to
do is up to the application, and the usual answer is to stop the pipeline,
destroy it and build a new one.

A Worker that is busy, not lost, for longer than `timeoutMs` counts as lost:
raise it for a node that legitimately takes longer.

Pings start with `pipe.start()`. Before that, while `Juturna.create()`,
`jt.pipeline()` and `pipe.start()` wait for the Workers, each of them has
`buildTimeoutMs` (5 minutes): long enough for the first `pipeline()` to fetch
the models of its nodes. A `create()` or `pipeline()` that runs out of time
rejects and terminates the instance; a `start()` loses the Workers that did not
answer.

### Restarting

```js
const jt = await Juturna.create({ supervise: { restart: { maxRestarts: 3, delayMs: 500 } } });
// ...
pipe.onWorkerLost(({ worker, willRestart }) => log(`${worker} lost`, willRestart));
pipe.onWorkerRestarted(({ worker, attempt }) => { input = pipe.input('in'); /* new ports, if you use any */ });
```

A restart builds the nodes of the Worker again from the same configuration,
connects its queues to the rest of the pipeline in both directions, and starts
it. It takes what starting a Worker takes: loading Pyodide, plus whatever the
nodes need in `warmup()`. The Worker is not pinged during that time:
it is supervised again once its nodes run. What bounds the restart is
`restart.timeoutMs` (30 seconds): a Worker that is not back by then is lost
again, which uses up an attempt. A node that loads a large model may need more.

What it does **not** bring back: the messages that were in the queues of the
lost Worker, and the state of its nodes, which start from scratch. Messages fed
to it in the meantime are dropped, or `feed()` throws if its node is the one
being restarted. The `MessagePort`s that were handed out for its input nodes
are dead; call `port()` again in `onWorkerRestarted`.

After `maxRestarts` the Worker stays lost. Leave it at 0 unless the nodes of
that Worker can come back from nothing: a node that runs out of memory will
run out again.

## Write a node

A node is a Juturna node that runs in Pyodide, built into the bundle with
`build/build.py --plugins`. [Write a browser node](write-a-node.md) walks
through one, from the plugin folder to the page.

## Models between visits

The example nodes keep their models and their `.wasm` runtimes in the
browser's Cache Storage (`juturna-models`): at the next visit each of those
files costs a request answered `304` (or a `200` with the same strong `ETag`, whose
body is not read), not a download, and a file that changed
on the server is downloaded again. `WhisperASR` and `TranslateOpus` route the
requests of transformers.js there too. The small JavaScript modules the nodes
load with `import()` are left to the browser's HTTP cache.

A page can fetch the files before the pipeline needs them, and show progress:

```js
import { Juturna, prefetch } from './src/juturna.js';

await prefetch(modelUrls, { onProgress: ({ url, loaded, total }) => bar.set(url, loaded, total) });
const jt = await Juturna.create();
const pipe = await jt.pipeline(config);   // the files are in the cache: 304s only
```

The README of each example node lists the files to pass. Await `prefetch`
before `jt.pipeline()`, or a file may be downloaded twice.

Nothing removes a file that is no longer asked for:
`caches.delete('juturna-models')`, or clearing the site data, empties the
cache. Pages that ran an older version of the transformers.js nodes also have a
`transformers-cache`, which is no longer read; `caches.delete('transformers-cache')`
removes it.

The browser may evict the cache when the disk runs short. A page that wants to
keep the models asks once with `navigator.storage.persist()` (the page, not a
Worker, can ask; Chrome answers without a prompt).

## Watch the messages

With `"telemetry": {"name": "browser"}` in the `pipeline` section of the
configuration, every Worker records the messages its nodes receive (`rx`) and
send (`tx`) and posts them to the page. Without the key the telemetry is off.

```js
const stop = pipe.onTelemetry(({ worker, records }) => { /* a batch as it is produced */ });
const latest = await pipe.telemetry();   // all Workers merged and sorted by ts
```

A record is `{ ts, evt, node, origin, msg_id, src_id, size, worker }`; the
[API reference](api.md#pipetelemetry-promiseobject) has the details. The
example pages turn it on with `?telemetry` and print a table per node (`rx`,
`tx`, bytes sent, `tx/s`), refreshed every second (`examples/telemetry.js`).

## A configuration is code

Treat a pipeline configuration as code of the page, not as data. The URLs a
node gets in its `configuration` are loaded as scripts: `person_mask` imports
the module at `ort_url`, `transcriber_kroko_wasm` evaluates the files at
`asr_helper_url` and `wasm_main_url`. They run in the Worker with the origin of
the page, so they can fetch whatever the page can. A configuration can also
build any node of the bundle, with any argument.

Never build a configuration, or a part of one, from what a user or another
site sends: write it in the page, and let the input choose among values the
page knows (a language, a model of a list), not supply URLs or node types.
