# Development

## Layout

```
src/         juturna.js (the API), juturna-worker.js (the Worker side),
             bootstrap.js (installs Juturna in Pyodide), ring.js (closes and repairs queues),
             model-cache.js (the files of the nodes kept between visits)
build/       build.py (the bundle), vendor.py (the third-party files nodes declare)
examples/    microphone.html, video-blur/, noise-suppression/, live-translation/,
             live-translation-kroko/, live-transcription-kroko/, telemetry.js (the
             `?telemetry` panel), plugins/ (nodes shared by more than one example)
test/        browser test pages, and test/plugins/ (nodes used by them)
serve.py     local server with the isolation headers
docs/        this documentation
```

## Build

```
python3 build/build.py --juturna /path/to/juturna --nodes /path/to/juturna_nodes
```

writes `dist/`: a wheel of Juturna built from the checkout as it is, uncommitted
changes included, `wheel.txt` with its name, and `plugins.zip` with the browser
nodes `BrowserInput` and `BrowserOutput` (from the juturna-nodes checkout). Run it again after any change in
the checkout.

Options: `--plugins DIR` (repeatable) adds the nodes under `DIR`: each is a folder
`_<name>` with `<name>.py` and `config.toml`. They are used in a pipeline as
`extensions.nodes.<Class>`, and `--test-plugins` adds the nodes of `test/plugins`.
`JUTURNA_REPO` can replace `--juturna`, `JUTURNA_NODES_REPO` `--nodes`. The bundle of the demo is:

```
python3 build/build.py --juturna <checkout> --nodes <nodes-checkout> --plugins examples/video-blur/plugins
```

`--plugins` repeats to combine several examples' nodes into one bundle
(one `serve.py` for all of them):

```
python3 build/build.py --juturna <checkout> --nodes <nodes-checkout> \
    --plugins examples/video-blur/plugins \
    --plugins examples/noise-suppression/plugins \
    --plugins examples/live-translation/plugins \
    --plugins examples/plugins
```

## Third-party files of the nodes

A node that loads files it does not ship (a model, a JavaScript runtime) lists
them in an `assets.toml` next to its code:

```toml
[[asset]]
url = "https://.../model.onnx"        # a fixed version, not a branch
path = "person_mask/selfie.onnx"      # relative to vendor/
sha256 = "44f328e2..."
license = "Apache-2.0"
```

`build/vendor.py` fetches them into `vendor/`, checking each checksum:

```
python3 build/vendor.py examples/video-blur/plugins      # every assets.toml under a folder
python3 build/vendor.py a/assets.toml b/assets.toml      # some manifests
python3 build/vendor.py pipeline.json --plugins my-nodes # the nodes a pipeline configuration uses
```

For a pipeline configuration, each `extensions.nodes.<Class>` node is looked up in
the folders given with `--plugins`, by the class its `_<name>/<name>.py` defines;
its `assets.toml`, if it has one, is used. The same file declared by several nodes
is fetched once; the same `path` with different contents is an error. A file that
is there and matches is not fetched again, one that does not match is an error
(`--force` replaces it), and a download that does not match its checksum is not
kept. `--dest` changes `vendor/`.

Where the files go is up to the page that uses the node: the node only gets URLs in
its configuration. The examples serve `vendor/` themselves, because a page with
`Cross-Origin-Embedder-Policy: require-corp` cannot load them from a host that
does not allow it. `assets.toml` is not part of `plugins.zip`.

At run time each Worker unpacks the wheel and `plugins.zip` into the
site-packages of its virtual file system with `unpackArchive` (see `src/bootstrap.js`): there is one wheel and
nothing to resolve, and a package manager would only add its load time. `av`,
`requests` and `grpc` have no Pyodide build and Juturna does not import them
unless a node needs them; `numpy` comes from Pyodide. The wheel and the archive
are fetched while Pyodide loads. `websockets` is not installed: no
pipeline imports it.

## Models read by transformers.js

`whisper_asr` and `translate_opus` load their models through the **remote**
branch of transformers.js (`env.allowRemoteModels = true`,
`env.remoteHost = models_url`), not its **local** one
(`env.localModelPath`): a bug in the tokenizer and processor existence check
of `@huggingface/transformers@4.3.0` rejects any `localModelPath` that is an
`http(s)` URL, the only form a browser can use, so the local branch never
loads `tokenizer.json`.

The same branch reads both layouts. With `models_url` set to
`https://huggingface.co/` and a `revision`, the node reads
`<model_id>/resolve/<revision>/`; with `models_url` pointing to `vendor/` and
no `revision`, it reads `<model_id>/` as `build/vendor.py` lays it out.
`examples/models.js` holds the revisions the demo pages use, the same commits
as the `assets.toml` of the two nodes.

## Tests

The tests are pages that run in the browser and write their outcome in
`window.__result`, with a `checks` object where every entry is `'ok'` or
`FAIL: ...`. Open one and read the result from the console, or from a script
driving the browser.

| Page | Bundle needed | What it checks |
|---|---|---|
| `test/bootstrap.html` | default | Juturna installs from the bundle; a pipeline runs |
| `test/facade.html` | `--test-plugins` | the API in one Worker: order, values, `copy`, `port()`, errors, status |
| `test/multi-worker.html` | `--test-plugins` | a pipeline across Workers, the stop order, isolation of a node that burns the CPU |
| `test/telemetry.html` | `--test-plugins` | `pipe.telemetry()` and `pipe.onTelemetry()` across two Workers with `{name: 'browser'}`, and the pipeline without the `telemetry` key |
| `test/large-frames.html` | `--test-plugins` | a 720p frame across Workers with a bigger `max_payload_bytes`, the error without it, and no limit inside a Worker |
| `test/local-queue.html` | default | queues local to a Worker: order, capacity, close, and the refusal to be shared |
| `test/supervisor.html` | `--test-plugins` | loss of a Worker: detection, closed queues, `stop()`; and the control without closing |
| `test/restart.html` | `--test-plugins` | a Worker lost and rebuilt: messages fed afterwards reach `out`; the second loss, with no restart left, is final |
| `test/lifecycle.html` | `--test-plugins` | listeners that throw during a loss and a restart, a warm-up longer than the timeout during a restart, a restart that never ends, a Worker that never answers `create()`, `pipeline()` or `start()`, `terminate()` and `destroy()` while a restart waits, timers slower than the timeout, a `create()` that fails, `status()` during a loss |
| `test/model-cache.html` | none | the cache behind `juturnaFetch`: a copy kept, used after a `304`, replaced when the file changed, used offline, and a failing cache falling back to the network |
| `test/ring-repair.html` | `--test-plugins` | a queue slot claimed and never filled stops the reader; `repairRing` frees it |
| `test/denoise.html` | `--plugins examples/noise-suppression/plugins`, and `build/vendor.py examples/noise-suppression/plugins` | `denoise_dfn`: chunks of any size, no sample lost, noise attenuated, faster than real time, a wrong rate refused |
| `test/live-translation.html` | `--plugins examples/live-translation/plugins --plugins examples/plugins`, and `build/vendor.py examples/live-translation/plugins examples/plugins` | `whisper_asr` and `translate_opus` across three Workers with silence and noise: nothing breaks on quiet audio, a wrong sampling rate is refused and the node keeps working |
| `test/video-blur.html` | `--test-plugins --plugins examples/video-blur/plugins`, and `build/vendor.py examples/video-blur/plugins` | the video pipeline with synthetic frames: `?fps=24&inflight=3` |
| `test/video-blur-canvas.html` | same as `video-blur.html` | same synthetic frames, but `background_blur` is dropped from the pipe and the compositing (background blur, soft mask edge) happens in the page's own canvas instead - compares directly against `video-blur.html`'s numbers |

Serve the pages with `python3 serve.py 8765` (see the [guide](guide.md)). A background tab limits `setTimeout` to once a second: the tests that need
regular timing take it from a Worker. `supervisor`, `restart` and `lifecycle`
expect a loss to be noticed within seconds: keep their tab in the foreground.
