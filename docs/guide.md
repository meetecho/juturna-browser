# Guide

This guide builds a first pipeline in a page, then covers the tasks that come
next: feeding audio and video, spreading nodes over several Workers, handling
a Worker that is lost, writing a node and watching the messages. How the
pieces work underneath is in [How it works](how-it-works.md); every function
is in the [API reference](api.md).

## Your first pipeline

**1. Build the bundle.** `dist/` holds a wheel of Juturna and the browser
nodes, built from checkouts of the `juturna` and `juturna-nodes` repositories:

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
up every other node of its Worker, so it belongs in a Worker of its own. In a
test, a probe crossing the pipeline had a median delay of 107 ms with a node
burning the CPU for 200 ms per message in the same Worker, and 2 ms with the
node in another. Each Worker costs memory (a Pyodide instance) and its start,
which happens in parallel with the others.

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
it. It takes what starting a Worker takes: about 3 seconds for Pyodide, plus
whatever the nodes need in `warmup()`. The Worker is not pinged during that time:
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

A node is a Juturna node. On a server you write it as described in the Juturna
documentation; in the browser it runs in Pyodide, so numpy is available and
most of what has native code is not. Put it in a plugin folder:

```
my-plugins/
  _my_node/
    my_node.py
    config.toml
```

`my_node.py` holds a class that extends `Node` (the folder is `_` plus the
module name), `config.toml` holds the default arguments under `[arguments]`.
Build the folder into the bundle with `build/build.py --plugins my-plugins`,
and use `type: 'extensions.nodes.MyNode'` (the class name) in the
configuration. `examples/video-blur/plugins` has two complete nodes, with a
README each.

A node can call JavaScript. `person_mask` loads onnxruntime-web and runs a
model that way: `run_js` evaluates a function, and `run_sync` waits for its
promise. `run_sync` works inside `warmup()` and `update()`, which run in a
context that may wait.

A node runs its `update()` for one message at a time and keeps the Worker's
thread while it does. Keep an eye on what it costs per message: at 24 fps it
must stay well under 42 ms, including the time to receive and send the frame
(about 1.5 ms per hop for 640×480 RGBA).

A node that loads files it does not ship, such as a model, declares them in an
`assets.toml`: see [Development](development.md#third-party-files-of-the-nodes).
It fetches them with `self.juturnaFetch(url)`, which keeps them in the browser
between visits (see [Models between visits](#models-between-visits)). A file
the node hands to a runtime, such as the `.wasm` of onnxruntime-web or of an
Emscripten build, is fetched the same way and passed over
(`ort.env.wasm.wasmBinary`, `Module.instantiateWasm`): left to the runtime, it
would be downloaded at every visit.

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
