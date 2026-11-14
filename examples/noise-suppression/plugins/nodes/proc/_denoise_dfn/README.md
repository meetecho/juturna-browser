# denoise_dfn

Removes the noise from speech with
[DeepFilterNet3](https://github.com/Rikorose/DeepFilterNet), run by
[onnxruntime-web](https://onnxruntime.ai/) from inside a Pyodide Worker, so it
works only with the browser transport.

## Node type: proc

## Node class name: DenoiseDFN

## Node name: denoise_dfn

## How it works

The model is a streaming graph: it takes one frame of 480 samples (10 ms at
48 kHz) and the state of the previous call, and returns the cleaned frame, the
new state and a local SNR estimate. The STFT, the ERB features and the deep
filtering are inside the graph. The state (45304 floats) is kept in JS.

The node holds back the samples that do not make a whole frame and prepends
them to the next message, so messages of any length can come in. A message that
does not complete a frame produces no output. The output has as many samples as
the frames processed, which is the input samples of the message plus the ones
held, rounded down to a multiple of 480.

## Arguments

- `ort_url`: absolute URL of the onnxruntime-web ES module (`ort.wasm.min.mjs`)
- `wasm_path`: absolute URL of the folder with the onnxruntime-web WASM files
- `model_url`: absolute URL of the streaming model (`dfn3.onnx` in `assets.toml`)
- `attenuation_db`: the most the noise is attenuated, in dB. Default 100, which
  leaves it to the model.

## Third-party files

Not shipped: onnxruntime-web 1.22.0 (MIT) and the DeepFilterNet3 model
(MIT OR Apache-2.0, torchDF export, at a fixed commit). `assets.toml` lists them
with URLs and checksums; `python3 build/vendor.py <plugins folder>` fetches them
into `vendor/`.

The node keeps `model_url` and `<wasm_path>ort-wasm-simd-threaded.wasm` in the
browser between visits: the list to pass to `prefetch()`.

## Input message

`Message[AudioPayload]`, mono, 48 kHz.

- Payload: `audio` (float32 in [-1, 1]), `sampling_rate` (must be 48000) and
  `channels` (must be 1, or -1 if unset), `start` (the seconds of the first
  sample; it is what the output times are computed from), `audio_format` (copied).
  `end` is not read. A different rate or more channels raise `ValueError` and
  the message is dropped.
- `meta`: no key is read. All of it is passed on.

## Output message

`Message[AudioPayload]`, at most one per input message.

- Payload: `audio` (cleaned, float32, a multiple of 480 samples), `sampling_rate`
  (48000), `channels` (1), `audio_format`, `start` (the input one, minus the
  time of the samples held back) and `end` (`start` plus the duration of `audio`).
- `meta`: the input `meta` plus `lsnr` (mean local SNR estimated by the model
  over the frames, in dB) and `ms_denoise` (milliseconds spent on the message).
