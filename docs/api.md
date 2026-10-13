# API reference

Everything is exported from `src/juturna.js`:

```js
import { Juturna } from './src/juturna.js';
```

The configuration of a pipeline is the JSON of Juturna on desktop, with the
keys described in [Configuration](#configuration).

## `Juturna`

### `Juturna.create(options?) → Promise<Juturna>`

Starts the Workers, loads Pyodide and installs Juturna in each of them, all in
parallel. It takes about 3 to 4 seconds, however many Workers there are.

| Option | Default | |
|---|---|---|
| `base` | `../dist/` (relative to `src/`) | Folder with the output of `build/build.py`. |
| `pyodide` | `'v314.0.6'` | Pyodide version, loaded from the jsDelivr CDN (no integrity check is possible on a dynamic `import()`). |
| `pyodideBase` | none | URL of a folder with a copy of that Pyodide release, served by the page: loaded from there instead of the CDN. |
| `workers` | `['main']` | Names of the Workers to start now. The ones a pipeline needs and are missing are started by `pipeline()`. |
| `supervise` | see below | How lost Workers are detected. |

`supervise` is an object with optional fields:

- `pingMs` (`1000`): how often each Worker is pinged, once the pipeline runs.
- `timeoutMs` (`5000`): a Worker that has not answered for this long is lost. A
  node that keeps the CPU busy for longer needs a higher value.
- `poisonRings` (`true`): whether the queues that lead to the nodes of a lost
  Worker are closed. `false` exists to test what closing them changes; do not
  use it otherwise.
- `restart` (`{maxRestarts: 0, delayMs: 500}`): with `maxRestarts` above 0, a
  lost Worker is built again after `delayMs`, at most that many times for each
  Worker. Off by default: a node that runs out of memory will do it again, and
  a loop of restarts is worse than a clean stop. See
  [Lost Workers](guide.md#lost-workers) for what a restart does and does not
  bring back.

### `jt.pipeline(config) → Promise<Pipeline>`

Builds and warms up the pipeline: it starts the Workers it needs, builds in each
of them the nodes it hosts, and connects the queues between Workers. One
pipeline per `Juturna` instance: a second call rejects.

It rejects when the configuration contains a cycle, and with the error of
Juturna when a node cannot be built (an unknown `type`, an invalid argument).

### `jt.terminate()`

Stops every Worker. The pipeline is gone. Call it after `pipe.destroy()`.

## `Pipeline`

### `pipe.input(name) → { feed, port }`

The handle of a `browser_input` node. It throws when `name` is not a
`browser_input` node of this pipeline. The handle stays valid when the Worker
of the node is rebuilt.

**`feed(message, options?)`** hands a message to the node. `message` is
`{kind, payload, meta}`, see [Messages](#messages).

- The buffers of the payload are **transferred**, not copied: after the call
  they are detached in the caller. Pass `{copy: true}` to keep using them. A view
  over part of a larger buffer (a `subarray`) is copied first, so the rest of that
  buffer is not detached.
- Messages of the same node reach it in the order they were fed.
- It throws when the Worker of the node was lost, or is being restarted. An
  invalid message does not throw: the error reaches `onError`.

**`port()`** returns a new `MessagePort` that feeds the node. Transfer it to
whatever produces the data (an `AudioWorklet`, another Worker) and it posts
`{kind, payload, meta}` messages straight to the Worker of the node, without
going through the page. The producer transfers the buffers it posts or they
are copied. A port is dead once the Worker of the node is rebuilt: ask for a
new one in `onWorkerRestarted`.

### `pipe.output(name) → { on }`

The handle of a `browser_output` node. It throws when `name` is not a
`browser_output` node of this pipeline.

**`on('message', callback) → unsubscribe`** calls `callback(message)` for every
message the node receives. `message` is `{kind, payload, meta, creator, id,
created_at}`; arrays are typed arrays. The callback runs on the page.

### `pipe.onError(callback) → unsubscribe`

Errors that happen while feeding data (an invalid message, a message that does
not fit the queues) and the loss of a Worker, as `Error` objects. Without a
listener they go to `console.error`.

### `pipe.onWorkerLost(callback) → unsubscribe`

Calls `callback({worker, reason, willRestart})` when a Worker is lost, see
[Lost Workers](guide.md#lost-workers). `willRestart` tells whether a new one is
being built.

### `pipe.onWorkerRestarted(callback) → unsubscribe`

Calls `callback({worker, attempt})` when a lost Worker has been built again and
its nodes run. They are new nodes: whatever state the old ones had is gone.

### `pipe.start() → Promise<void>`

Starts the nodes of every Worker and starts pinging the Workers. A pipeline
that was stopped cannot be started again: destroy it and build another.

### `pipe.stop() → Promise<void>`

Stops the pipeline in the same order as on desktop, across Workers: the nodes of
each layer of the graph are sent a stop and joined before the next layer, so
what an upstream node sent last is still consumed downstream. It takes about
two seconds per node at the moment. Lost Workers are skipped.

### `pipe.destroy() → Promise<void>`

Releases the nodes. It stops the pipeline first if it is running.

### `pipe.status() → Promise<object>`

```js
{
  pipeline: 'pipeline_running',            // the states of the Workers, joined by '/'
  nodes: {
    mask: { status: 'component_running',
            health: { update_failures: 0, worker_failures: 0,
                      source_failures: 0, last_failure_at: null } },
    // ...
  },
  workers: { main: 'pipeline_running', ml: 'restarting', cpu: 'lost' },
  lost: { cpu: 'no answer for 5000 ms' },  // only the lost Workers
}
```

The nodes of a lost or restarting Worker are not listed.

## Configuration

The keys of Juturna that matter here, in a pipeline configuration:

```js
{
  pipeline: {
    name: 'blur', id: 'blur-1',
    folder: '/tmp/juturna/blur',            // a path in the virtual file system of Pyodide
    transport: 'browser',                   // required; or an object, see below
    nodes: [ /* ... */ ],
    links: [ { from: 'in', to: 'mask' } ],
  },
}
```

- **`pipeline.transport`** is `'browser'`, or an object `{name: 'browser',
  ...options}` with:

  | Option | Default | |
  |---|---|---|
  | `max_payload_bytes` | 2000000 | Size of the payload of a message that crosses to another Worker. A message that does not fit fails with an error that names this key. Inside a Worker the queues hold the messages as they are, and the limit does not apply. A 640×480 RGBA frame is 1.2 MB, a 1280×720 one is 3.7 MB. |
  | `max_meta_json_bytes` | 4096 | Size of the metadata of a message, as JSON. |
  | `queue_capacity` | 8 | Messages a queue holds before the sender waits. |
  | `remote_timeout` | 30 | Seconds a node waits for a node of another Worker to be connected. |

  Reading a message costs what the message weighs, not what `max_payload_bytes`
  says, so setting it to the biggest message of the pipeline costs no time. It
  does reserve the address space: 15 MB per queue at the default. Only the
  queues written to from another Worker are rings: the inbound queue of a node
  with an upstream in a different Worker. Every other queue is local.

- **`nodes[].worker`** names the Worker the node runs in (`main` when missing).
  Nodes of different Workers are linked as any other.
- **`nodes[].type`** is the class of the node: `BrowserInput` and
  `BrowserOutput` come with juturna-nodes; the others are added with
  `build/build.py --plugins` and are named `extensions.nodes.<Class>`.

## Messages

`kind` is one of:

| `kind` | `payload` |
|---|---|
| `audio` | `audio` (`Float32Array`, or `Int16Array`, normalised to [-1, 1]), `sampling_rate`, `channels`, `start`, `end` |
| `image` | `image` (flat `Uint8Array`), `width`, `height`, `depth`, `pixel_format`, `timestamp` |
| `bytes` | `cnt` (`Uint8Array`) |
| `object` | any JSON-compatible fields |

`meta` is any JSON-compatible object, and it travels with the message through
the whole pipeline. Sampling rate, chunking and timestamps are the business of
whoever feeds the pipeline: nothing in the nodes is configured about the page.

An image is rebuilt as `(height, width, depth)` in the nodes, so `width`,
`height` and `depth` must be set for a node to see anything but a flat array.
An unknown `kind`, or an unknown field, is an error: it reaches `onError` and
the message is dropped.

## Errors, in short

| What | Where it shows |
|---|---|
| Invalid configuration, a node that cannot be built | `jt.pipeline()` rejects |
| Invalid message, message too big for the queues | `pipe.onError` |
| A Python exception inside a node | Logged by Juturna; `status().nodes[...].health` counts it. The node keeps running. |
| Loss of a Worker | `pipe.onWorkerLost` and `pipe.onError`; `status()`; `pipe.onWorkerRestarted` if it comes back |
| `feed()` or `port()` to a lost Worker | throws |
