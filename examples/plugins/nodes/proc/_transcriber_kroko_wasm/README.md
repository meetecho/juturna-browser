# transcriber_kroko_wasm

Transcribes mono, 16 kHz speech into text incrementally, with
[Kroko](https://kroko.ai)'s streaming Zipformer (en, community model,
CC-BY-SA), run by
[sherpa-onnx-wasm](https://k2-fsa.github.io/sherpa/onnx/wasm/index.html)
from inside a Pyodide Worker, so it works only with the browser transport.

## Node type: proc

## Node class name: TranscriberKrokoWasm

## Node name: transcriber_kroko_wasm

## How it works

Unlike `whisper_asr` (this project's other ASR node, which accumulates a
fixed-size window and transcribes it whole, with an overlap carried into
the next window), this is a real streaming transducer: every call feeds it
another chunk of audio, and the model's own internal state - kept entirely
in JS, inside a sherpa-onnx `OnlineStream`, never round-tripped to Python -
carries across calls. There is no window/overlap bookkeeping in this node
at all. Every call returns the best transcript of the current utterance
*so far*; `meta['final']` tells the difference between "still updating"
(the model's endpoint detector has not fired) and "this utterance is done"
(it fired - the C++ side has already reset its own stream for the next
utterance by the time this node's `update()` returns, see `_STEP`'s own
`reset(stream)` call). A message never produces more than one output
message, and an empty transcript is dropped, not transmitted, same as
`whisper_asr`.

There is no VAD and no language selection: the loaded model is English
only, and endpointing (deciding an utterance is over) is the model's own
`enableEndpoint`/`rule*MinTrailingSilence` logic, not a separate node.

`stop()` flushes whatever the model's internal state still holds for the
utterance in progress (`OnlineStream.inputFinished()`, then decoded to
completion) and transmits it with `meta['final'] = True` before the
underlying stream is torn down - otherwise, audio spoken right before the
pipeline is stopped (anything since the last endpoint) would be silently
lost: the model's own endpoint detector needs trailing silence to fire,
which a user hitting Stop mid-sentence never provides. This flush message
has no triggering input message, so its `meta` carries only `final`
(no `ms_transcribe`, nothing copied forward) and its payload's
`start`/`end` are both the `end` of the last audio chunk processed
(`-1.0`, the payload default, if `stop()` runs before any chunk ever
was).

No `max_threads` argument, unlike this project's other nodes: this
build (`build-wasm-simd-asr.sh`, no `USE_PTHREADS`) is single-threaded -
verified by grepping the compiled `sherpa-onnx-wasm-main-asr.js` for
`pthread` (zero matches) - so there is no thread pool here to cap.

## Arguments

- `asr_helper_url`: absolute URL of sherpa-onnx-wasm's JS glue for the
  online ASR API (`sherpa-onnx-asr.js`) - defines
  `createOnlineRecognizer` and the `OnlineRecognizer`/`OnlineStream`
  classes this node calls into.
- `wasm_main_url`: absolute URL of the compiled Emscripten entry point
  (`sherpa-onnx-wasm-main-asr.js`); its `.wasm` and `.data` (the latter
  holding the Kroko encoder/decoder/joiner/tokens, baked in at build
  time - see "Building the WASM runtime") must sit next to it.

## Building the WASM runtime

Unlike this project's other JS/WASM dependencies (onnxruntime-web,
transformers.js, the ONNX models `person_mask`/`denoise_dfn` load),
sherpa-onnx-wasm is **not** something `build/vendor.py` can fetch: the
model is compiled *into* the `.wasm`/`.data` at build time (an Emscripten
`--preload-file`), so there is no single stable URL an `assets.toml`
`[[asset]]` entry could point at and checksum - the artifact is unique to
the (model, sherpa-onnx version) pair used to build it, and has to be
produced locally. There is deliberately no `assets.toml` in this
directory for that reason.

`build_wasm.sh` in this directory reproduces it:

```
./build_wasm.sh [-m MODEL_URL] [-wd WORKDIR]
```

It needs Emscripten (not part of this project's usual toolchain - the
script checks for `emcc` and exits with instructions if missing), git,
cmake, and about 2 GB of free disk for the sherpa-onnx source tree and
build directory (put in `WORKDIR`, a temp dir by default - not in this
repo). It downloads the 4 Kroko model files (~71 MB total: `encoder.onnx`,
`decoder.onnx`, `joiner.onnx`, `tokens.txt`) from
[csukuangfj/sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06](https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06)
on HuggingFace (a standard, non-encrypted sherpa-onnx model export -
distinct from Kroko's own commercial WASM SDK, which wraps its paid
models in a licensed/encrypted container this build does not use), then
runs sherpa-onnx's own `build-wasm-simd-asr.sh`. Both sources are
fixed in the script (`SHERPA_ONNX_TAG` and the revision in `MODEL_URL`), so
that two builds give the same files: change them there to move to a newer
sherpa-onnx or model. A full build (`-j8`,
mirrored by the script) took about 6 minutes on a 12-core machine, most
of it compiling sherpa-onnx's C++ core.

At the end it prints the 4 files to vendor, always together (they
reference each other by relative path):

- `sherpa-onnx-asr.js` (JS glue, from the sherpa-onnx source tree itself,
  not the build output)
- `sherpa-onnx-wasm-main-asr.js`
- `sherpa-onnx-wasm-main-asr.wasm`
- `sherpa-onnx-wasm-main-asr.data` (the model - ~68 MB)

### Vendoring these files

Copy all 4 into `vendor/transcriber_kroko_wasm/` (the path this demo's
`index.html` points `asr_helper_url`/`wasm_main_url` at) - there is no
`vendor.py` step for this node. `vendor/` is already gitignored, so this
is a one-time local step, same as any other vendored asset in this repo,
just fetched by running `build_wasm.sh` instead of `vendor.py`.

Swapping in a different sherpa-onnx online-transducer model (a different
language, Kroko's larger models, or an unrelated streaming Zipformer)
only requires re-running `build_wasm.sh` with those 4 `.onnx`/`.txt`
files in `sherpa-onnx/wasm/asr/assets/` instead - this node's own code
does not hardcode anything Kroko-specific beyond the README you are
reading.

## Input message

`Message[AudioPayload]`, mono, 16 kHz.

- Payload: `audio` (float32 in [-1, 1]), `sampling_rate` (must be 16000)
  and `channels` (must be 1, or -1 if unset), `start`/`end` (seconds,
  copied unchanged into the output payload - not read for any
  computation, unlike `whisper_asr`, since there is no window to
  timestamp). `audio_format` is not read. A different rate or more
  channels raise `ValueError` and the message is dropped.
- `meta`: no key is read. All of it is passed on to the output message,
  when one is produced.

## Output message

`Message[ObjectPayload]`, zero or one per input message.

- Payload: `text` (the transcript accumulated so far in the current
  utterance, stripped, never empty), `start`/`end` (seconds, copied from
  the input message).
- `meta`: the input `meta` plus `final` (bool - whether the model's
  endpoint detector fired on this call, ending the utterance and
  resetting its internal state for the next one) and `ms_transcribe`
  (milliseconds spent on this call).
