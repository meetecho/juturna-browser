# Demos

| Demo | Try |
|---|---|
| [Microphone](#microphone) | <a class="try-it" href="../examples/microphone.html">▶ Try it</a> |
| [Background blur](#background-blur) | <a class="try-it" href="../examples/video-blur/index.html">▶ Try it</a> <a class="try-it" href="../examples/video-blur/canvas.html">▶ Canvas version</a> |
| [Noise suppression](#noise-suppression) | <a class="try-it" href="../examples/noise-suppression/index.html">▶ Try it</a> |
| [Live translation](#live-translation) | <a class="try-it" href="../examples/live-translation/index.html">▶ Try it</a> <a class="try-it" href="../examples/live-translation/text.html">▶ Text version</a> |
| [Streaming transcription](#live-transcription-and-translation-with-kroko) | <a class="try-it" href="../examples/live-transcription-kroko/index.html">▶ Try it</a> |
| [Streaming transcription and translation](#live-transcription-and-translation-with-kroko) | <a class="try-it" href="../examples/live-translation-kroko/index.html">▶ Try it</a> |

On the documentation site the demos run as they are, from the buttons above.
From a clone of the repository they need the local server described in
[Run them locally](#run-them-locally).

Six demos, eight pages. Each one runs entirely in the tab: the camera and the
microphone are processed where they are captured, and no server receives
them. All but the microphone one run real models. Add `?telemetry` to the URL
of any of them to see the messages each node receives and sends, live under
the page. How the demos are built is in the [Guide](guide.md).

## Microphone

<a class="try-it" href="../examples/microphone.html">▶ Try it</a>

The microphone audio goes through a pipeline and comes back to the page,
which shows the chunks received, their level and any that arrive out of order.
It is the smallest complete page to start from.

## Background blur

The webcam image comes back with the background blurred: a portrait
segmentation model finds the person, and everything else is blurred.

<a class="try-it" href="../examples/video-blur/index.html">▶ Try it</a>
<a class="try-it" href="../examples/video-blur/canvas.html">▶ Canvas version</a>

The main page asks the camera for 24 fps (`?fps=` changes it) and drops frames
when the pipeline falls behind, so the delay does not build up (`?inflight=`
sets how many frames may be in flight, three by default). The canvas version
looks the same and blurs on the page instead of in the pipeline.

Measured on a 12-core desktop, Chrome 157, at commit `db0897a` (2026-11-14). The synthetic rows are the median of three runs; the webcam rows are one session, medians of the last 60 frames:

| Run | Frames | Median delay | Steps |
|---|---|---|---|
| `test/video-blur.html?fps=24&inflight=3`, synthetic 640×480 frames | 24.7 fps, 2 of 73 frames dropped | 51 ms | 17 ms segmentation, 21 ms blur |
| Same, at 30 fps | 30 fps, 4 of 71 frames dropped | 54 ms | 19 ms segmentation, 23 ms blur |
| Webcam at 24 fps | 24.1 fps, 8 of 2186 frames dropped | 70 ms | 24 ms segmentation, 26 ms blur |
| `test/video-blur-canvas.html?fps=24&inflight=3`, synthetic frames | 0 dropped (2 with `video-blur.html`) | 33 ms (51 ms with `video-blur.html`) | 8 ms of canvas compositing instead of 21 ms of numpy blur |
| `canvas.html`, webcam at 24 fps | 23.8 fps, 0 frames dropped | 26 ms | 16 ms segmentation, 2.9 ms of canvas compositing |

## Noise suppression

<a class="try-it" href="../examples/noise-suppression/index.html">▶ Try it</a>

The noise is removed from the speech captured by the microphone, with the
DeepFilterNet3 model. `?synthetic=1` uses a voice-like tone with steady noise
instead of the microphone; `?attenuation=12` lets some noise through. Another
attenuation can be tried on the audio already recorded.

## Live translation

<a class="try-it" href="../examples/live-translation/index.html">▶ Try it</a>
<a class="try-it" href="../examples/live-translation/text.html">▶ Text version</a>

English speech, or typed text, becomes a live transcript and a translation
into Italian, Spanish, Chinese or German, with the Whisper and OPUS-MT models.

- The main page transcribes the microphone and translates the transcript. The
  target language (`?target=`), the transcription window (`?window=`) and the
  capture chunk are set before pressing Start; changing the target language
  needs Stop, since it picks a different model.
- The text version translates what is typed in a text box. The translation of
  the line being typed updates as it changes (500 ms debounce by default,
  `?debounce=`); Enter commits it to the history and starts a new line.

Loading the two models takes about 2.7 s. On the JFK sample (11 s, fed in real
time in 1 s chunks), a 4 s window takes 1.8 s to transcribe and 0.4 s to
translate: its translation arrives 2.2 s after the chunk that closed the
window.

## Live transcription and translation with Kroko

<a class="try-it" href="../examples/live-transcription-kroko/index.html">▶ Try transcription</a>
<a class="try-it" href="../examples/live-translation-kroko/index.html">▶ Try translation</a>

- Transcription: English speech from the microphone is transcribed with
  Kroko's streaming model. Unlike the Whisper demo, it transcribes as the audio
  arrives: each 100 ms chunk updates the current line, and the line is final
  when the model detects the end of the utterance.
- Translation: the same transcription, with each final line translated.

On the JFK sample, fed in real time in 100 ms chunks, each chunk takes under
1 ms to transcribe, and a final line arrives about 140 ms after the chunk that
ends the utterance. Loading the model takes about 3 s.

On the translation page `?maxThreads=` sets the threads of the translation;
the transcription is single-threaded.

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
