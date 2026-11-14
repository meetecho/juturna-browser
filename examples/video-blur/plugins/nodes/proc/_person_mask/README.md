# person_mask

Segments the person in a video frame and puts the mask in the alpha channel.
Runs [onnxruntime-web](https://onnxruntime.ai/) from inside a Pyodide Worker,
so it works only with the browser transport.

## Node type: proc

## Node class name: PersonMask

## Node name: person_mask

## Arguments

- `ort_url`: absolute URL of the onnxruntime-web ES module (`ort.wasm.min.mjs`)
- `wasm_path`: absolute URL of the folder with the onnxruntime-web WASM files
- `model_url`: absolute URL of the model; it takes `uint8` RGB as
  `[1, height, width, 3]` and returns `float32` alphas as `[1, height, width, 1]`

## Third-party files

The node loads two things at run time and does not ship them:

- **onnxruntime-web** 1.22.0 (MIT): `ort.wasm.min.mjs`, `ort-wasm-simd-threaded.mjs`
  (which it loads by itself) and `ort-wasm-simd-threaded.wasm` (which the node
  fetches and hands over). They go in the folder `wasm_path` points to, next to
  `ort_url`.
- **A segmentation model** with the interface above. The one in `assets.toml` is
  [MediaPipe Selfie Segmentation converted to ONNX](https://huggingface.co/onnx-community/mediapipe_selfie_segmentation-web)
  (Apache-2.0), at a fixed commit. A model that needs another input, or a heavier
  one, has its own cost: MODNet, for instance, took 127 ms at 256×256.

`assets.toml` lists them with their URLs and checksums, and
`python3 build/vendor.py <plugins folder or pipeline.json>` fetches them into
`vendor/`. Serve them from wherever the page can load them: with
`Cross-Origin-Embedder-Policy: require-corp` a host must allow it, which is why
the examples serve them locally.

The node keeps `model_url` and `<wasm_path>ort-wasm-simd-threaded.wasm` in the
browser between visits: the list to pass to `prefetch()`.

## Input message

`Message[ImagePayload]` with an RGBA frame.

- Payload: `image` (`uint8`, `(height, width, 4)`) and `timestamp`. The RGB
  channels are read; the alpha channel is ignored. `width`, `height` and
  `pixel_format` are not read.
- `meta`: no key is read. All of it is passed on.

## Output message

`Message[ImagePayload]`, one per input message.

- Payload: `image` is the input frame with the mask in the alpha channel
  (0 = background, 255 = person); `width`, `height`, `depth` (4),
  `pixel_format` (`rgba`) and `timestamp` (the input one).
- `meta`: the input `meta` plus `ms_segment`, the milliseconds spent on the
  frame.
