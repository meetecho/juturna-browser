# whisper_asr

Transcribes mono, 16 kHz speech into text with
[Whisper](https://github.com/openai/whisper), run by
[transformers.js](https://huggingface.co/docs/transformers.js) (on top of
onnxruntime-web) from inside a Pyodide Worker, so it works only with the
browser transport.

## Node type: proc

## Node class name: WhisperASR

## Node name: whisper_asr

## How it works

Whisper is not a streaming model: it needs a whole window of audio to attend
over, unlike `denoise_dfn`. The node accumulates incoming audio and, once it
holds `window_seconds` of it, transcribes that window and keeps the last
`overlap_seconds` as the start of the next one, so that speech near a window
boundary is not cut in the middle. A message may produce zero, one, or (if it
completes more than one window at once) several output messages.

There is no VAD: a window is transcribed whether or not it holds speech (an
empty transcript is dropped, not transmitted), and a word that straddles two
windows may be recognised twice, once at the end of one transcript and once
at the start of the next. Whisper's own language token is set from `language`
at every call; the language is not auto-detected or read from the message.

## Arguments

- `transformers_url`: absolute URL of the transformers.js module
  (`transformers.min.js`)
- `wasm_mjs_url`, `wasm_bin_url`: absolute URLs of the onnxruntime-web WASM
  loader and binary (`ort-wasm-simd-threaded.asyncify.{mjs,wasm}`) that this
  version of transformers.js depends on; the onnxruntime-web already vendored
  for `person_mask`/`denoise_dfn` does not work here (different WASM ABI, see
  `assets.toml`)
- `models_url`: absolute URL of the folder holding `<model_id>/`
- `model_id`: model folder name under `models_url`, default
  `Xenova/whisper-base`
- `language`: spoken language Whisper is told to expect (English name, e.g.
  `english`), default `english`
- `window_seconds`: duration of audio transcribed at once, default `4.0`
- `overlap_seconds`: audio carried from one window into the next, default
  `0.5`; must be less than `window_seconds`
- `max_threads`: cap on the onnxruntime-web WASM threads of the node's
  Worker; 0 (default) leaves it to onnxruntime-web, `min(4, ceil(cores / 2))`

## Third-party files

Not shipped: transformers.js 4.3.0 (Apache-2.0), the onnxruntime-web dev
build it depends on (MIT), and the Whisper base model, multilingual,
quantized (MIT, at a fixed commit). `assets.toml` lists them with URLs and
checksums; `python3 build/vendor.py <plugins folder>` fetches them into
`vendor/`.

At run time the node fetches, under `models_url/<model_id>/`, `config.json`,
`generation_config.json`, `preprocessor_config.json`, `tokenizer.json`,
`tokenizer_config.json`, `onnx/encoder_model_quantized.onnx` and
`onnx/decoder_model_merged_quantized.onnx`, plus `wasm_bin_url` and
`wasm_mjs_url`: the list to pass to `prefetch()`. They are kept in the browser
between visits.

## Input message

`Message[AudioPayload]`, mono, 16 kHz.

- Payload: `audio` (float32 in [-1, 1]), `sampling_rate` (must be 16000) and
  `channels` (must be 1, or -1 if unset), `start` (the seconds of the first
  sample of the message; only read on the first call after the buffer was
  empty, to timestamp the current window). `end` and `audio_format` are not
  read. A different rate or more channels raise `ValueError` and the message
  is dropped.
- `meta`: no key is read. All of it is passed on to every output message this
  input contributes to (an input that completes more than one window
  contributes its `meta` to each of them).

## Output message

`Message[ObjectPayload]`, zero to several per input message, one per
non-empty transcribed window.

- Payload: `text` (the transcript, stripped, never empty), `language` (the
  configured one), `start` and `end` (seconds, the window's span).
- `meta`: the input `meta` plus `ms_transcribe` (milliseconds spent
  transcribing the window).
