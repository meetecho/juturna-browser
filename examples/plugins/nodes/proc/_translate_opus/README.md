# translate_opus

Translates text with an [OPUS-MT](https://github.com/Helsinki-NLP/OPUS-MT-train)
(Marian) model, run by
[transformers.js](https://huggingface.co/docs/transformers.js) (on top of
onnxruntime-web) from inside a Pyodide Worker, so it works only with the
browser transport.

## Node type: proc

## Node class name: TranslateOpus

## Node name: translate_opus

## How it works

Each source/target language pair is its own model
(`Xenova/opus-mt-<src>-<tgt>`); `model_id`, `source_lang` and `target_lang`
must name the same pair the node was configured (and vendored) for. Unlike
`whisper_asr`, there is no state or buffering: one input message is one
translation call, independent of every other message.

## Arguments

- `transformers_url`: absolute URL of the transformers.js module
  (`transformers.min.js`)
- `wasm_mjs_url`, `wasm_bin_url`: absolute URLs of the onnxruntime-web WASM
  loader and binary (`ort-wasm-simd-threaded.asyncify.{mjs,wasm}`); same
  build as `whisper_asr`, see its README for why the version already vendored
  for `person_mask`/`denoise_dfn` does not work here
- `models_url`: absolute URL of the folder holding `<model_id>/`
- `model_id`: model folder name under `models_url`, default
  `Xenova/opus-mt-en-it`
- `source_lang`, `target_lang`: language codes of the pair, default `en`/`it`

## Third-party files

Not shipped: transformers.js 4.3.0 (Apache-2.0), the onnxruntime-web dev
build it depends on (MIT), and the OPUS-MT models for `en >it`, `en >fr` and
`en >zh`, quantized (Apache-2.0, at a fixed commit each). `assets.toml` lists
them with URLs and checksums; `python3 build/vendor.py <plugins folder>`
fetches them into `vendor/`. Only the pair `model_id` names is loaded at run
time; the other two stay on disk unused unless another node instance, or a
restart with a different configuration, asks for them.

At run time the node fetches, under `models_url/<model_id>/`, `config.json`,
`generation_config.json`, `tokenizer.json`, `tokenizer_config.json`,
`onnx/encoder_model_quantized.onnx` and
`onnx/decoder_model_merged_quantized.onnx`, plus `wasm_bin_url` and
`wasm_mjs_url`: the list to pass to `prefetch()`. They are kept in the browser
between visits.

## Input message

`Message[ObjectPayload]`.

- Payload: `text` (required, a non-empty string to translate; an empty or
  missing value raises `ValueError`).
- `meta`: `final`, default `True` if absent - a message with `final: False`
  (a partial result from a streaming source, e.g. `transcriber_kroko_wasm`)
  is dropped without translating or transmitting. All of `meta` is passed on
  unchanged on a message that is translated.

## Output message

`Message[ObjectPayload]`, one per input message whose `meta['final']` is not
`False`.

- Payload: `text` (the translation), `source_text` (the input `text`),
  `source_lang`, `target_lang` (the configured pair).
- `meta`: the input `meta` plus `ms_translate` (milliseconds spent
  translating).
