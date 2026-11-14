# API reference

Everything is exported from `src/juturna.js`:

```js
import { Juturna, prefetch } from './src/juturna.js';
```

The configuration of a pipeline is the JSON of Juturna on desktop, with the
keys described in [Configuration](#configuration).

## `Juturna`

### `Juturna.create(options?): Promise<Juturna>`

Starts the Workers, loads Pyodide and installs Juturna in each of them, all in
parallel. It takes about 3 to 4 seconds, however many Workers there are. It
rejects, and leaves no Worker running, when a Worker fails to start or does
not answer within `supervise.buildTimeoutMs`.

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
  node that keeps the CPU busy for longer needs a higher value. The time the
  page's own timer did not run does not count: a Worker is lost after it missed
  `timeoutMs / pingMs` pings in a row, whenever they were sent. In a background
  tab, where timers run once a second, and in a hidden one, where they run once
  a minute, that takes longer than `timeoutMs`: minutes, with the defaults, in
  a hidden tab.
- `buildTimeoutMs` (`300000`): the time each of `Juturna.create()`,
  `jt.pipeline()` and `pipe.start()` has. Nothing pings a Worker before its
  nodes run, so this is what notices one that vanished during them. It counts
  the download of the nodes' models in the first `pipeline()`: raise it for a
  page with heavy models on slow connections.
- `poisonRings` (`true`): whether the queues that lead to the nodes of a lost
  Worker are closed. `false` exists to test what closing them changes; do not
  use it otherwise.
- `restart` (`{maxRestarts: 0, delayMs: 500, timeoutMs: 30000}`): with
  `maxRestarts` above 0, a lost Worker is built again after `delayMs`, at most
  that many times for each Worker. Off by default: a node that runs out of memory will do it again, and
  a loop of restarts is worse than a clean stop. A restart has `timeoutMs`,
  from the start of the new Worker to its nodes running: past it the Worker is
  lost again, and the next attempt follows if one is left. Raise it when the
  nodes of a Worker take longer than that to warm up; it is a number of
  milliseconds, and the limit cannot be removed. See
  [Lost Workers](guide.md#lost-workers) for what a restart does and does not
  bring back.

### `jt.pipeline(config): Promise<Pipeline>`

Builds and warms up the pipeline: it starts the Workers it needs, builds in each
of them the nodes it hosts, and connects the queues between Workers. One
pipeline per `Juturna` instance: a second call rejects.

It rejects when the configuration contains a cycle, and with the error of
Juturna when a node cannot be built (an unknown `type`, an invalid argument);
the instance can then build another pipeline. It also rejects when it takes
longer than `supervise.buildTimeoutMs` (`pipeline not built within ... ms`):
the instance is then terminated, a further `pipeline()` on it rejects, and the
page creates another instance.

### `jt.terminate()`

Stops every Worker. The pipeline is gone, and a restart that was waiting is
cancelled. Call it after `pipe.destroy()`.

## `Pipeline`

### `pipe.input(name): { feed, port }`

The handle of a `BrowserInput` node. It throws when `name` is not a
`BrowserInput` node of this pipeline. The handle stays valid when the Worker
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

### `pipe.output(name): { on }`

The handle of a `BrowserOutput` node. It throws when `name` is not a
`BrowserOutput` node of this pipeline.

**`on('message', callback)`** calls `callback(message)` for every
message the node receives. `message` is `{kind, payload, meta, creator, id,
created_at}`; arrays are typed arrays. The callback runs on the page. It returns
the function that removes the listener.

### `pipe.onError(callback): unsubscribe`

Errors that happen while feeding data (an invalid message, a message that does
not fit the queues) and the loss of a Worker, as `Error` objects. Without a
listener they go to `console.error`.

### `pipe.onWorkerLost(callback): unsubscribe`

Calls `callback({worker, reason, willRestart})` when a Worker is lost, see
[Lost Workers](guide.md#lost-workers). `willRestart` tells whether a new one is
being built.

### `pipe.onWorkerRestarted(callback): unsubscribe`

Calls `callback({worker, attempt})` when a lost Worker has been built again and
its nodes run. They are new nodes: whatever state the old ones had is gone.

### `pipe.onTelemetry(callback): unsubscribe`

Listens to the telemetry of the Workers, a batch at a time as it is produced:
`callback({ worker, records })`. The pipeline needs
`"telemetry": {"name": "browser"}` in its configuration.
A callback that throws does not keep the others from the batch: its error
reaches `onError`.
Batches are delivered as they arrive, and the records are not reordered: those
of one Worker are in the order it produced them, but their `ts` can still go
backwards a few times, and batches of different Workers interleave. Sort by `ts`,
or use `pipe.telemetry()`, which does.

### `pipe.start(): Promise<void>`

Starts the nodes of every Worker and starts pinging the Workers. A Worker that
does not answer within `supervise.buildTimeoutMs` is lost (`not started within
... ms`), and restarted if `supervise.restart` allows it. A pipeline that was
stopped cannot be started again: destroy it and build another.

### `pipe.stop(): Promise<void>`

Stops the pipeline in the same order as on desktop, across Workers: the nodes of
each layer of the graph are sent a stop and joined before the next layer, so
what an upstream node sent last is still consumed downstream. It takes about
two seconds per node at most (the join timeout of Juturna). Lost Workers are skipped.
A restart under way is waited for first, up to `restart.timeoutMs`; `destroy()`
does the same.

### `pipe.destroy(): Promise<void>`

Releases the nodes. It stops the pipeline first if it is running. No Worker
is restarted from then on.

### `pipe.telemetry(): Promise<object[]>`

The latest records, all Workers merged and ordered by `ts` (10000 per Worker
by default, see `max_records` in [Configuration](#configuration): the oldest are
dropped). Empty when there is no `telemetry` key. Lost and
restarting Workers are skipped, and a restarted Worker starts again with no
records.

```js
{ ts: 1791991365.069,   // seconds, from time.time() (1 ms resolution)
  evt: 'rx',            // 'rx' or 'tx'
  node: 'burn', origin: 'in',
  msg_id: 3, src_id: 3, // id of the message the sender was processing when it
                        // sent this one (null if none)
  size: 640,            // payload bytes
  worker: 'heavy' }
```

The message ids are counters of one Worker: identify a message by
`(origin, msg_id)`, not by `msg_id` alone.

### `pipe.status(): Promise<object>`

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

## `prefetch(urls, options?): Promise<void>`

Fetches files into the cache the nodes read from (`juturna-models`, see
`self.juturnaFetch` below), so that `jt.pipeline()` finds them there. It needs
no `Juturna` instance: the page and its Workers share the cache.

```js
await prefetch(urls, { onProgress: ({ url, loaded, total }) => show(url, loaded, total) });
```

- `urls`: the files, as URLs or strings. The README of each example node lists
  the files it fetches.
- `onProgress({url, loaded, total})`: called as the bytes of a file arrive,
  and once more when it is stored, with `loaded === total`. During the download
  `total` comes from the `Content-Length` of the answer, `null` when the server
  does not send it or compresses the file. A file already kept and unchanged
  gets only that last call, once the server has answered `304` (both `null` if
  its size is not known).

It resolves once every file is stored, and rejects with an error that names
the URL of the first file that failed; the others keep downloading and are
stored. Await it
before `jt.pipeline()`: a node that asks for a file `prefetch` is still
fetching downloads it a second time.

## In a Worker: `self.juturnaFetch(url): Promise<Response>`

For the JavaScript a node runs: fetches `url` like `fetch()`, and keeps the
file in the browser's Cache Storage (`juturna-models`) for the next visit. When
a copy is there, it asks the server whether the file changed (a conditional
request on its `Last-Modified` or `ETag`): an answer of `304` returns the copy,
and so does a `200` with the same strong `ETag`, whose body is dropped unread
(the CDN Hugging Face sends large files from ignores the condition). A new file
replaces the copy, and a network error or a server error (`5xx`) returns
the copy. A server that sends neither header gets the file downloaded at
every visit.

The file is stored as it arrives and the caller gets the stored copy, so it is
kept by the time the promise resolves. Requests for the same file at the same
time share one download, and a file checked once in a page or a Worker is not
checked again there (transformers.js asks for some files twice).

Any other error answer (`404`) is returned as it is and not kept; a failure of
the cache itself (no Cache Storage, out of quota) falls back to the network. A
node that also runs outside juturna-browser uses `self.juturnaFetch ?? fetch`.

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

- **`pipeline.telemetry`** is `{name: 'browser', ...options}`: each Worker keeps
  the records of its nodes and posts them to the page, which receives them in
  `pipe.onTelemetry()` and `pipe.telemetry()`. Without the key the telemetry is
  off. `max_records` (10000) is the number of records each Worker keeps. The
  `memory` manager of Juturna is accepted too, but it posts nothing to the
  page. `csv` is refused: it needs a shared file system, which the browser
  transport does not offer, and `jt.pipeline()` rejects.
- **`nodes[].worker`** names the Worker the node runs in (`main` when missing).
  Nodes of different Workers are linked as any other.
- **`nodes[].configuration`** holds the arguments of the node. The URLs in it
  are loaded as scripts: see [A configuration is code](guide.md#a-configuration-is-code)
  before building one from anything the page did not write.
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
| A Worker that does not answer before the pipeline runs | `Juturna.create()` or `jt.pipeline()` rejects; in `pipe.start()`, `pipe.onWorkerLost` |
| Invalid message, message too big for the queues | `pipe.onError` |
| A Python exception inside a node | Logged by Juturna; `status().nodes[...].health` counts it. The node keeps running. |
| A callback of `onTelemetry` or `output().on` that throws | `pipe.onError` |
| Loss of a Worker | `pipe.onWorkerLost` and `pipe.onError`; `status()`; `pipe.onWorkerRestarted` if it comes back |
| A callback of `onWorkerLost` or `onWorkerRestarted` that throws | `pipe.onError`; the recovery goes on |
| `feed()` or `port()` to a lost Worker | throws |
