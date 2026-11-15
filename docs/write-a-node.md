# Write a browser node

This page takes a node from an empty folder to a page where it runs between
`BrowserInput` and `BrowserOutput`. It follows the two nodes of the background
blur demo: `background_blur`, which needs nothing but numpy, and `person_mask`,
which runs a segmentation model through a JavaScript library.

<a class="try-it" href="../examples/video-blur/index.html">▶ Try it</a>

## Before you start

- A bundle that builds and a page that runs: see
  [Your first pipeline](guide.md#your-first-pipeline).
- A browser node is a Juturna node. Its lifecycle (`warmup()`, `update()`,
  `transmit()`) is described in the
  [Juturna documentation](https://github.com/meetecho/juturna).
- For the import check of step 4, a Python with juturna and numpy installed.

## 1. Lay out the plugin folder

The two nodes of the demo live in one plugin folder:

```
examples/video-blur/plugins/
  nodes/proc/
    _background_blur/
      background_blur.py
      config.toml
      README.md
    _person_mask/
      person_mask.py
      config.toml
      assets.toml
      README.md
```

`build/build.py` takes as a node every folder `_<name>` that holds a
`config.toml` and a `<name>.py`, at any depth under the plugin folder: the
`nodes/proc/` levels are a convention, not a requirement. Only the `.py` and
`.toml` files go into the bundle, and `assets.toml` stays out of it (step 7).

## 2. Write the node class

`config.toml` lists the arguments a configuration can set, with their defaults:

```toml
[arguments]
downscale = 4
radius = 2
passes = 3

[meta]
```

The class extends `Node` and takes the same arguments:

```python
class BackgroundBlur(Node[ImagePayload, ImagePayload]):
    def __init__(
        self, downscale: int = 4, radius: int = 2, passes: int = 3, **kwargs
    ):
        super().__init__(**kwargs)
```

The class name is the node type: a configuration uses
`type: 'extensions.nodes.BackgroundBlur'`. `build.py` registers the first
`class <Name>(Node` of the module.

The node gets only the keys listed under `[arguments]`. A key the configuration
sets and `config.toml` does not list is dropped without an error
(`python -m juturna validate` warns about it), so an argument that is missing
there keeps its Python default whatever the page passes.

`update()` receives one message, builds the output and sends it:

```python
result = Message[ImagePayload](
    creator=self.name,
    payload=ImagePayload(image=out, width=width, height=height, depth=4,
                         pixel_format='rgba', timestamp=message.payload.timestamp),
)
result.meta.update(message.meta)
result.meta['ms_blur'] = round((time.perf_counter() - started) * 1000, 1)

self.transmit(result)
```

Copying `meta` keeps what the page attached to the frame, such as the time it
was fed.

## 3. Stay within Pyodide

Code that runs on a server can fail in a Worker for three reasons.

**No threads of its own.** Pyodide has no Python threads: the loops of the
nodes in a Worker are tasks of one event loop, and `update()` holds that loop
until it returns or waits. A node that starts a `threading.Thread` does not
work. A JavaScript runtime the node calls can still use its own WASM threads:
`person_mask` sets the thread count of onnxruntime-web.

**Only what Pyodide builds.** numpy and the packages Pyodide ships are
available; a package with native code that Pyodide does not build is not, and
nothing is installed at run time. `background_blur` does its blur in numpy, in
16-bit integers.

**A time budget per message.** While `update()` runs, no other node of its
Worker does. At 24 fps a video node must stay well under 42 ms per frame,
including the time to receive and send it: for a 640×480 RGBA frame, about
1.5 ms between two Workers and 0.5 ms for one more node in the same Worker
([What each step costs](how-it-works.md#what-each-step-costs)).
`background_blur` writes its own time in `meta['ms_blur']`, so the page can
watch it.

## 4. Build it into the bundle

Pass the plugin folder to `build.py`, and run it again after every change to
the node:

```
python3 build/build.py --juturna /path/to/juturna --nodes /path/to/juturna_nodes \
    --plugins examples/video-blur/plugins
```

`--plugins` repeats, to put the nodes of several folders in one bundle. Then
check that the node module imports outside the browser, as
`python -m juturna validate` needs:

```
python build/check_nodes.py
```

`check_nodes.py` covers `examples/` and `test/plugins`; a node elsewhere is
checked by `python -m juturna validate` on a configuration that uses it.

## 5. Try it in a page

Put the node between the two ends of a pipeline and feed it frames:

```js
const config = { pipeline: { name: 'blur', id: 'blur-1', folder: '/tmp/juturna/blur',
  transport: 'browser',
  nodes: [{ name: 'in',   type: 'BrowserInput',  configuration: {} },
          { name: 'blur', type: 'extensions.nodes.BackgroundBlur', configuration: {} },
          { name: 'out',  type: 'BrowserOutput', configuration: {} }],
  links: [{ from: 'in', to: 'blur' }, { from: 'blur', to: 'out' }] } };

const jt   = await Juturna.create();
const pipe = await jt.pipeline(config);
pipe.output('out').on('message', ({ payload, meta }) => console.log(meta.ms_blur));
await pipe.start();
const { data } = canvas.getContext('2d').getImageData(0, 0, 640, 480);   // a 640×480 canvas
pipe.input('in').feed({ kind: 'image', payload: { image: new Uint8Array(data.buffer),
  width: 640, height: 480, depth: 4, pixel_format: 'rgba', timestamp: 0 }, meta: {} });
```

`background_blur` reads the person mask from the alpha channel. A camera frame
has alpha 255 everywhere, so it comes back unchanged: enough to see the message
cross the node and to read `ms_blur`.

A Python exception inside `update()` does not reach `onError`: Juturna logs it
and the node keeps running. Read it from `pipe.status()`:

```js
(await pipe.status()).nodes.blur.health.update_failures   // 0 when every message went through
```

With `"telemetry": {"name": "browser"}` in the `pipeline` section, the Workers
also report every message each node receives and sends. The example pages turn
it on with `?telemetry` in the URL: see
[Watch the messages](guide.md#watch-the-messages).

## 6. Call a JavaScript library

A segmentation model has no Pyodide package, but onnxruntime-web runs it in
JavaScript. `person_mask` calls it from Python with `run_js`, which evaluates
JavaScript source and returns the function it defines, and `run_sync`, which
waits for a promise:

```python
def warmup(self):  # noqa: D102
    from pyodide.code import run_js
    from pyodide.ffi import run_sync

    self._runtime = run_sync(
        run_js(_LOAD)(
            self._ort_url,
            self._wasm_path,
            self._model_url,
            self._max_threads,
        )
    )
    self._infer = run_js(_INFER)
```

`_LOAD` is an async JavaScript function, kept in the module as a string, that
imports onnxruntime-web from `ort_url` and creates the session. `run_sync`
works inside `warmup()` and `update()`, which juturna-browser runs in a context
that may wait.

`js` and `pyodide` are imported inside the functions that use them, never at
the top of the module. `python -m juturna validate` resolves a node type by
importing its module with CPython, where neither exists: with a top-level
import the module fails, `validate` reports `cannot resolve type`, and the
node's logic cannot be tested with pytest.

Data crosses the boundary by copy. `update()` hands the frame over with
`to_js()` and reads the mask back with `.to_py()`:

```python
alphas = run_sync(
    self._infer(
        self._runtime,
        to_js(np.ascontiguousarray(frame).reshape(-1)),
        height,
        width,
    )
)
mask = np.array(alphas.to_py(), dtype=np.float32).reshape(height, width)
```

The node does not know where the page serves the library and the model, so
their URLs are arguments, empty in `config.toml`. `max_threads` caps the WASM
threads of onnxruntime-web; TOML has no null, so its default is 0, which the
node reads as `None` (onnxruntime-web's own choice):

```toml
[arguments]
ort_url = ""
wasm_path = ""
model_url = ""
max_threads = 0
```

The page passes absolute URLs, and `null` for `max_threads` when its field is
empty:

```js
const url = (path) => new URL(path, location.href).href;

{ name: 'mask', type: 'extensions.nodes.PersonMask', worker: 'ml',
  configuration: { ort_url: url('../../vendor/person_mask/ort/ort.wasm.min.mjs'),
                   wasm_path: url('../../vendor/person_mask/ort/'),
                   model_url: url('../../vendor/person_mask/selfie.onnx'),
                   max_threads: maxThreads } }
```

## 7. Declare third-party files

A page with `Cross-Origin-Embedder-Policy: require-corp` cannot load a file
from a host that does not allow it, so the examples serve the library and the
model from `vendor/`. The node lists them in an `assets.toml` next to its code,
each with a fixed version and its checksum:

```toml
[[asset]]
url = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/ort.wasm.min.mjs"
path = "person_mask/ort/ort.wasm.min.mjs"
sha256 = "6ef726f355b791129f7ddf3f62e7877a16b9b777abe87004b8ab306e6b9cf265"
license = "MIT"
```

`build/vendor.py` downloads them into `vendor/` and refuses a file whose
checksum does not match:

```
python3 build/vendor.py examples/video-blur/plugins
```

A model from Hugging Face is pinned to a commit in its URL
(`.../resolve/<commit>/onnx/model.onnx`), not to a branch that can change
under the checksum. The other ways to call `vendor.py`, and what it does with
a file that is already there, are in
[Development](development.md#third-party-files-of-the-nodes).

## 8. Keep the files between visits

Fetched with `fetch()` or left to the runtime, the model and the WASM runtime
depend on the browser's HTTP cache: whether the next visit downloads them again
is up to the headers of the server and to what the cache keeps.
`self.juturnaFetch(url)` fetches like `fetch()` and keeps the file in a Cache
Storage of its own (`juturna-models`). At the next visit it asks the server
whether the file changed: a `304`, or a `200` with the same strong `ETag` (the
CDN of Hugging Face ignores the condition), returns the copy without reading
the body, and so does a network or server error. `_LOAD` uses it for the model
and for the runtime, which it hands to onnxruntime-web instead of letting it
fetch the file on its own:

```js
const get = self.juturnaFetch ?? fetch;
// ...
const runtime = new URL('ort-wasm-simd-threaded.wasm', wasmPath).href;
ort.env.wasm.wasmBinary = await bytes(runtime);
const model = new Uint8Array(await bytes(modelUrl));
```

An Emscripten build takes its `.wasm` the same way through
`Module.instantiateWasm` (see `transcriber_kroko_wasm`). `?? fetch` keeps the
code working outside juturna-browser. The README of the
node lists the files it keeps, so that a page can download them ahead with
`prefetch()` and show progress: see
[Models between visits](guide.md#models-between-visits). For a node that loads
its model through transformers.js, see
[Models read by transformers.js](development.md#models-read-by-transformersjs).

## 9. Choose a Worker

With the webcam at 24 fps the demo measured 24 ms of segmentation and 26 ms
of blur per frame ([Demos](demos.md#background-blur)): 50 ms, more than the
42 ms budget of one Worker. The demo gives each node a Worker with the
`worker` key:

```js
const jt = await Juturna.create({ workers: ['main', 'ml', 'cpu'] });
// ...
{ name: 'mask', type: 'extensions.nodes.PersonMask',     worker: 'ml',  configuration: { /* ... */ } },
{ name: 'blur', type: 'extensions.nodes.BackgroundBlur', worker: 'cpu', configuration: {} },
```

A node without the key runs in `main`. Each Worker costs a Pyodide instance;
the measurements are in
[Run nodes in several Workers](guide.md#run-nodes-in-several-workers).

## 10. Document the node

A `README.md` next to the code tells the page what to feed and what comes out.
The example nodes use the same sections:

- `Node type`, `Node class name`, `Node name`;
- `Arguments`, with their defaults;
- `Third-party files`, for a node with an `assets.toml`: what it loads, the
  licenses, and the files to pass to `prefetch()`;
- `Input message`: the payload fields the node reads, and the `meta` keys;
- `Output message`: how many messages per input, the payload, and the `meta`
  keys the node adds.

`examples/video-blur/plugins/nodes/proc/_background_blur/README.md` is a short
one to start from.

## Check it works

1. `python build/check_nodes.py` prints `ok` for the node, or, for a node
   outside `examples/` and `test/plugins`, `python -m juturna validate` accepts
   a configuration that uses it.
2. `build.py` with `--plugins` ends without an error, and the page builds the pipeline:
   `jt.pipeline()` rejects when the type cannot be resolved.
3. Messages come out of `BrowserOutput`, and
   `(await pipe.status()).nodes.<name>.health.update_failures` stays at 0.
4. With `?telemetry`, the node has as many `tx` as `rx` (for a node that sends
   one message per input).

For the demo nodes, run the commands of steps 4 and 7, start
`python3 serve.py 8765` and open the demo with `?telemetry`.

Look up the message formats and `status()` in the [API reference](api.md).
