"""
WhisperASR

Proc node transcribing speech with Whisper, run by transformers.js (on top of
onnxruntime-web) from inside the Pyodide Worker: the model is a JS/WASM
runtime called from Python, not a Python package.

Unlike a streaming model (see `denoise_dfn`), Whisper is not called sample by
sample: it needs a whole window of audio to attend over. The node accumulates
incoming audio and runs the model on fixed-size, overlapping windows, keeping
the tail of one window as the start of the next so that speech is not cut at
a window boundary. There is no VAD here: a window is transcribed whether or
not it holds speech, and a word that straddles two windows may be recognised
twice, once at the end of one transcript and once at the start of the next.
"""

import time

import numpy as np

from juturna.components import Message
from juturna.components import Node

from juturna.payloads import AudioPayload
from juturna.payloads import ObjectPayload

SAMPLING_RATE = 16000

_LOAD = """
(async (transformersUrl, wasmMjsUrl, wasmBinUrl, modelsUrl, modelId, revision, maxThreads) => {
  const { pipeline, env } = await import(transformersUrl);
  env.allowLocalModels = false;
  env.allowRemoteModels = true;
  env.remoteHost = modelsUrl;
  // a revision means a Hugging Face layout, none the vendor/ one
  env.remotePathTemplate = revision ? '{model}/resolve/{revision}/' : '{model}/';
  env.backends.onnx.wasm.wasmPaths = { mjs: wasmMjsUrl, wasm: wasmBinUrl };
  // juturna-browser's cache, checked at every visit, instead of the one of
  // transformers.js: in 4.3.0 env.fetch carries the model files and the
  // runtime. Anything but a plain GET (its probe of a file's size is a
  // Range request) goes as it is.
  if (self.juturnaFetch) {
    const plain = (init) => (init?.method ?? 'GET') === 'GET'
      && !new Headers(init?.headers).has('Range');
    env.useBrowserCache = false;
    env.fetch = (url, init) =>
      plain(init) ? self.juturnaFetch(url) : fetch(url, init);
  }
  const cores = navigator.hardwareConcurrency || 4;
  env.backends.onnx.wasm.numThreads =
    maxThreads ?? Math.min(4, Math.ceil(cores / 2));
  return await pipeline('automatic-speech-recognition', modelId, {
    dtype: 'q8',
    ...(revision && { revision }),
  });
})
"""

_TRANSCRIBE = """
(async (asr, samples, language) => {
  const out = await asr(samples, { language, task: 'transcribe' });
  return out.text;
})
"""


class WhisperASR(Node[AudioPayload, ObjectPayload]):
    """Transcribe mono, 16 kHz speech into text, window by window."""

    def __init__(
        self,
        transformers_url: str,
        wasm_mjs_url: str,
        wasm_bin_url: str,
        models_url: str,
        model_id: str = "Xenova/whisper-base",
        language: str = "english",
        window_seconds: float = 4.0,
        overlap_seconds: float = 0.5,
        revision: str = "",
        max_threads: int | None = None,
        **kwargs,
    ):
        """
        Parameters
        ----------
        transformers_url : str
            Absolute URL of the transformers.js module
            (``transformers.min.js``).
        wasm_mjs_url : str
            Absolute URL of the onnxruntime-web WASM loader
            (``ort-wasm-simd-threaded.asyncify.mjs``).
        wasm_bin_url : str
            Absolute URL of the matching WASM binary
            (``ort-wasm-simd-threaded.asyncify.wasm``).
        models_url : str
            Absolute URL of the folder holding ``<model_id>/`` (vendored by
            ``build/vendor.py``), passed to transformers.js as
            ``env.remoteHost`` (see the comment on ``_LOAD`` for why it is
            not ``env.localModelPath``).
        model_id : str
            The model folder name under ``models_url``, e.g.
            ``Xenova/whisper-base``.
        language : str
            Spoken language Whisper is told to expect (its English name, e.g.
            ``english``), not auto-detected.
        window_seconds : float
            Duration of audio transcribed at once.
        overlap_seconds : float
            How much of a window is carried into the next one, so that speech
            near the boundary is not cut. Must be less than ``window_seconds``.
        revision : str
            Commit of the model repository on Hugging Face, with ``models_url``
            set to ``https://huggingface.co/``: the files are read from
            ``<model_id>/resolve/<revision>/``. Empty (default) for a folder
            laid out by ``build/vendor.py``.
        max_threads : int | None
            Cap on onnxruntime-web's WASM thread pool for this node's
            Worker. ``None`` uses the same ``min(4, ceil(cores / 2))`` a
            plain onnxruntime-web default would pick. Worth lowering when
            this node shares a pipeline with another WASM-threaded node
            (e.g. ``translate_opus``): each node picks its thread count
            independently, so two nodes running at once can together
            request more threads than the machine has cores.
        kwargs : dict
            Superclass arguments.

        Raises
        ------
        ValueError
            If ``overlap_seconds`` is negative or not less than
            ``window_seconds``.

        """
        super().__init__(**kwargs)

        self._transformers_url = transformers_url
        self._wasm_mjs_url = wasm_mjs_url
        self._wasm_bin_url = wasm_bin_url
        self._models_url = models_url
        self._model_id = model_id
        self._revision = revision
        self._language = language
        self._window = int(window_seconds * SAMPLING_RATE)
        self._overlap = int(overlap_seconds * SAMPLING_RATE)

        # in samples, as update() counts: an overlap as long as the window
        # would never let it move on
        if not 0 <= self._overlap < self._window:
            raise ValueError(
                f"overlap_seconds ({overlap_seconds}) must be at least 0 and "
                f"less than window_seconds ({window_seconds})"
            )
        self._max_threads = max_threads

        self._asr = None
        self._transcribe = None
        self._audio = np.zeros(0, dtype=np.float32)
        self._window_start = 0.0

    def warmup(self):  # noqa: D102
        from pyodide.code import run_js
        from pyodide.ffi import run_sync

        self._asr = run_sync(
            run_js(_LOAD)(
                self._transformers_url,
                self._wasm_mjs_url,
                self._wasm_bin_url,
                self._models_url,
                self._model_id,
                self._revision,
                self._max_threads,
            )
        )
        self._transcribe = run_js(_TRANSCRIBE)

        self.logger.info("whisper model loaded")

    def update(self, message: Message[AudioPayload], **kwargs):  # noqa: D102
        from pyodide.ffi import run_sync
        from pyodide.ffi import to_js

        payload = message.payload

        if payload.sampling_rate != SAMPLING_RATE or payload.channels > 1:
            raise ValueError(
                f"{self.name} needs mono audio at {SAMPLING_RATE} Hz, got "
                f"{payload.channels} channel(s) at {payload.sampling_rate} Hz"
            )

        if not len(self._audio):
            self._window_start = payload.start

        self._audio = np.concatenate(
            [self._audio, payload.audio.astype(np.float32, copy=False)]
        )

        while len(self._audio) >= self._window:
            started = time.perf_counter()

            chunk = np.ascontiguousarray(self._audio[: self._window])
            text = run_sync(
                self._transcribe(self._asr, to_js(chunk), self._language)
            ).strip()

            if text:
                out = Message[ObjectPayload](
                    creator=self.name,
                    payload=ObjectPayload(
                        text=text,
                        language=self._language,
                        start=self._window_start,
                        end=self._window_start + self._window / SAMPLING_RATE,
                    ),
                )
                out.meta.update(message.meta)
                elapsed = time.perf_counter() - started
                out.meta["ms_transcribe"] = round(elapsed * 1000, 1)

                self.transmit(out)

            kept = self._overlap
            self._window_start += (self._window - kept) / SAMPLING_RATE
            self._audio = self._audio[self._window - kept :]
