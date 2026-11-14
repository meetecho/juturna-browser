# Demos

Six pages in `examples/` use the same API, and all but the first run real
models:
`Juturna.create()`, `pipe.input().feed()`, `pipe.output().on('message')`.
Each heavy node has a Worker of its own. Add `?telemetry` to the URL of any of
them to see the messages each node receives and sends, live under the page.

## Run them locally

One bundle serves every demo:

```
python3 build/vendor.py examples/video-blur/plugins examples/noise-suppression/plugins examples/live-translation/plugins examples/plugins
python3 build/build.py --juturna /path/to/juturna --nodes /path/to/juturna_nodes \
    --plugins examples/video-blur/plugins \
    --plugins examples/noise-suppression/plugins \
    --plugins examples/live-translation/plugins \
    --plugins examples/plugins
python3 serve.py 8765
```

`build/vendor.py` fetches into `vendor/` the files the nodes declare in their
`assets.toml`, checking each checksum. The speech and translation models are
read from Hugging Face, at the commits those files pin; add `?models=vendor`
to the URL to read them from `vendor/` instead, for example to work offline.
The Kroko demos also need a WebAssembly build of the model, made with the
script described in the README of `transcriber_kroko_wasm`.

A demo needs only its own nodes: `build/vendor.py` and `--plugins` take the
folders of that demo alone.

`index.html`, at the root of the repository, links every demo and shows the
measured numbers.

## Microphone

<http://localhost:8765/examples/microphone.html>: the microphone goes through
a pipeline of `BrowserInput` and `BrowserOutput`, plus an image round trip.
The page shows the chunks received, their level and any that arrive out of
order. It is the smallest complete page to start from.

## Background blur

Webcam frames go through a pipeline of three Workers: `person_mask` runs a
portrait segmentation model with onnxruntime-web and writes the mask in the
alpha channel, `background_blur` blurs what the mask marks as background
(numpy), and the result is drawn on a `<canvas>`.

<http://localhost:8765/examples/video-blur/index.html> asks the camera for
24 fps (`?fps=` changes it). The page keeps at most three frames in flight
(`?inflight=`) and drops the others, so the delay does not build up when the
pipeline is slower than the camera.

<http://localhost:8765/examples/video-blur/canvas.html> is the same pipeline
without `background_blur`: only `person_mask` runs, and the page's own canvas
does the compositing (`filter: blur()` for the background, `drawImage`
respecting the per-pixel alpha of the mask for the soft edge).

Measured on a 12-core desktop:

| Run | Frames | Median delay | Steps |
|---|---|---|---|
| `test/video-blur.html?fps=24&inflight=3`, synthetic 640×480 frames | 24.6 fps | 64 ms | 20 ms segmentation, 22 ms blur |
| Same, at 30 fps | 29.2 fps, 6% of the frames dropped | | |
| Webcam at 24 fps | 24 fps | 72 ms | 21 ms segmentation, 26 ms blur |
| `test/video-blur-canvas.html?fps=24&inflight=3`, synthetic frames | 0 dropped (2 with `video-blur.html`) | 40 ms (60 ms with `video-blur.html`) | 8.8 ms of canvas compositing instead of 22 ms of numpy blur |

Compositing on the canvas saves a Worker and loses nothing: the segmentation
is the same.

## Noise suppression

<http://localhost:8765/examples/noise-suppression/index.html>: the microphone
goes through `denoise_dfn`, which removes the noise from speech with
DeepFilterNet3 run by onnxruntime-web. `?synthetic=1` uses a voice-like tone
with steady noise instead of the microphone; `?attenuation=12` lets some noise
through. The attenuation is fixed when the node warms up, so the page builds a
new pipeline to try another value on the audio it already recorded.

## Live translation

English speech, or typed text, becomes a live transcript and a translation,
through two nodes on transformers.js and onnxruntime-web, each in its own
Worker: `whisper_asr` (Whisper, speech to English text) and `translate_opus`
(OPUS-MT, English to Italian, Spanish, Chinese or German).

- <http://localhost:8765/examples/live-translation/index.html>: the microphone,
  then `whisper_asr`, then `translate_opus`. The target language
  (`?target=`), the transcription window (`?window=`) and the capture chunk are
  set before pressing Start; changing the target language needs Stop, since it
  picks a different model.
- <http://localhost:8765/examples/live-translation/text.html>: a text box feeds
  `translate_opus` alone, with an `object` message (`{kind: 'object', payload:
  {text}}`; `decode_message` builds an `ObjectPayload` from it), the same
  shape `translate_opus` reads from `whisper_asr`. The
  translation of the line being typed overwrites itself (500 ms debounce by
  default, `?debounce=`); Enter commits it to the history and starts a new
  line.

A model's Worker takes about 2.5 s on the first load. A 4 s window of
transcription and translation together takes about 3 s, on the JFK sample also
used by `test/live-translation-demo-jfk.html`.

## Live transcription and translation with Kroko

- <http://localhost:8765/examples/live-transcription-kroko/index.html>: the
  microphone goes through `transcriber_kroko_wasm`, Kroko's streaming
  Zipformer for English run by sherpa-onnx compiled to WebAssembly. Unlike
  `whisper_asr`, it transcribes as the audio arrives: each 100 ms chunk updates
  the current line, and the line is final when the model detects the end of
  the utterance.
- <http://localhost:8765/examples/live-translation-kroko/index.html>: the same
  transcription followed by `translate_opus`, which translates only the final
  lines.

The WebAssembly build is single-threaded, so the transcription page has no
thread setting; on the translation page `?maxThreads=` applies to
`translate_opus` only.

## Models and licenses

| Demo | Model | License |
|---|---|---|
| Background blur | MediaPipe selfie segmentation | Apache-2.0 |
| Noise suppression | [DeepFilterNet3](https://github.com/Rikorose/DeepFilterNet) | MIT or Apache-2.0 |
| Live translation | [Whisper base](https://huggingface.co/openai/whisper-base), ONNX by Xenova | Apache-2.0 |
| Live translation | [OPUS-MT](https://huggingface.co/Helsinki-NLP) en-it, en-es, en-zh, ONNX by Xenova | Apache-2.0 |
| Live translation | [OPUS-MT en-de](https://huggingface.co/Helsinki-NLP/opus-mt-en-de), ONNX by Xenova | CC-BY-4.0 |
| Kroko | [Kroko streaming Zipformer (en)](https://huggingface.co/Banafo/Kroko-ASR) by Banafo, converted for sherpa-onnx by [csukuangfj](https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06) | CC-BY-SA (community model) |

The `assets.toml` of each node lists every file with its URL, checksum and
license.
