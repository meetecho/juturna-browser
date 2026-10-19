# Guide

## How it works

A pipeline runs in Pyodide Workers. The page never runs a node: it hands
messages to the pipeline and receives messages from it.

```
page                Worker "main"                Worker "ml"          Worker "cpu"
 |  feed()            BrowserInput                 person_mask       background_blur
 |------------------>     |                           |                     |
 |                        +--- shared-memory queue --->+-- queue ----------->+
 |                                                                          |
 |<--- postMessage ---------------------------------------------------------+ (via main)
```

- Each Worker loads Pyodide and Juturna, and builds the nodes the configuration
  assigns to it. Juturna is the library as it is on desktop, with the browser
  transport instead of threads.
- The messages between nodes travel through queues on `SharedArrayBuffer`. A
  node writes to a node of another Worker as to any other: Juturna hides the
  queue. Several Workers can write to the same node.
- The page and the Workers talk with `postMessage`. `feed()` transfers the
  buffers of a message (zero copy) and `on('message')` gets a typed array.

The page must be served with `Cross-Origin-Opener-Policy: same-origin` and
`Cross-Origin-Embedder-Policy: require-corp`, otherwise `SharedArrayBuffer` does
not exist. `serve.py` does it.

## A first pipeline

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
the page feeds and what it receives. Between them go the nodes that do the work.

## Feeding audio from the microphone

The page captures the audio; `examples/microphone.html` is a complete example.
Capturing in an `AudioWorklet` and posting to a `port()` keeps the main thread
out of the way:

```js
const port = input.port();                                   // a MessagePort
workletNode.port.postMessage({ port }, [port]);              // hand it to the worklet
// in the worklet: port.postMessage({ kind: 'audio', payload: { audio, sampling_rate: 16000 } }, [audio.buffer]);
```

## Feeding video

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

## Several Workers

Give a node a `"worker"` and it runs there:

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
test, a probe crossing the pipeline had a median delay of 132 ms with a node
burning the CPU for 200 ms per message in the same Worker, and 4 ms with the
node in another. Each Worker costs memory (a Pyodide instance) and its start,
which happens in parallel with the others.

The workers of a pipeline are stopped in the order of the graph, so a Worker
that still holds messages for a downstream node is stopped first, and the
downstream node consumes them.

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
4. the queues it was writing to are repaired, see below.

The rest of the pipeline keeps running, and `stop()` and `destroy()` work on
it. By default nothing restarts on its own and no state is recovered: what to do
is up to the application, and the usual answer is to stop the pipeline, destroy
it and build a new one.

A Worker that dies while it writes a message has claimed a place in a queue
and not filled it, and the node that reads that queue would wait for it for
ever. The page fills in the place with an empty message, which the reader
skips. It does so only for a place that stays claimed and unfilled for 250 ms,
much longer than a write takes.

A Worker that is busy, not lost, for longer than `timeoutMs` counts as lost:
raise it for a node that legitimately takes longer.

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
whatever the nodes need in `warmup()`.

What it does **not** bring back: the messages that were in the queues of the
lost Worker, and the state of its nodes, which start from scratch. Messages fed
to it in the meantime are dropped, or `feed()` throws if its node is the one
being restarted. The `MessagePort`s that were handed out for its input nodes
are dead; call `port()` again in `onWorkerRestarted`.

After `maxRestarts` the Worker stays lost. Leave it at 0 unless the nodes of
that Worker can come back from nothing: a node that runs out of memory will
run out again.

## Writing a node

A node is a Juturna node. On desktop you write it as described in the Juturna
documentation; in the browser it runs in Pyodide, so numpy is available and
most of what has native code is not. Put it in a plugin folder:

```
my-plugins/
  _my_node/
    my_node.py
    config.toml
```

`my_node.py` holds a class that extends `Node` (the folder is `_` plus the module name),
`config.toml` holds the default arguments under `[arguments]`. Build the
folder into the bundle with `build/build.py --plugins my-plugins`, and use
`type: 'extensions.nodes.MyNode'` (the class name) in the configuration. `examples/video-blur/plugins` has two
complete nodes, with a README each.

A node can call JavaScript. `person_mask` loads onnxruntime-web and runs a model
that way: `run_js` evaluates a function, and `run_sync` waits for its promise.
`run_sync` works inside `warmup()` and `update()`, which run in a context that
may wait.

A node runs its `update()` for one message at a time and keeps the Worker's
thread while it does. Keep an eye on what it costs per message: at 24 fps it
must stay well under 42 ms, including the time to receive and send the frame
(about 1 ms per hop for 640×480 RGBA).
