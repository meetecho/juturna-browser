"""
TranscriberKrokoWasm

Proc node transcribing speech incrementally with Kroko's streaming Zipformer
(en, 2025-08-06), run by sherpa-onnx-wasm from inside the Pyodide Worker: the
model is a JS/WASM runtime called from Python, not a Python package.

Unlike `whisper_asr` (fixed-size window, transcribed whole), this is a
real streaming transducer: every call feeds it more audio and returns the
transcript of the utterance *so far*. `meta['final']` marks an endpoint
(see `_STEP`). See this node's README for details and for how its model
is built (baked into `wasm_main_url`'s `.data`, not fetched at run time).
"""

import time

import numpy as np

from pyodide.code import run_js
from pyodide.ffi import run_sync
from pyodide.ffi import to_js

from juturna.components import Message
from juturna.components import Node

from juturna.payloads import AudioPayload
from juturna.payloads import ObjectPayload

SAMPLING_RATE = 16000

# Two classic (non-ES-module) Emscripten scripts, loaded with
# fetch()+indirect eval: a module Worker has no importScripts(), and
# indirect eval still runs in global scope, so `Module`/
# `createOnlineRecognizer` land on globalThis as a <script> load would.
_LOAD = """
(async (asrHelperUrl, mainUrl) => {
  self.Module = {};
  // Emscripten's scriptDirectory auto-detection needs a <script>/
  // importScripts() context, which eval doesn't give it - pin it so
  // .wasm/.data resolve next to the vendored main script.
  Module.locateFile = (path) => new URL(path, mainUrl).href;

  const readyPromise = new Promise((resolve, reject) => {
    Module.onRuntimeInitialized = () => resolve();
    Module.onAbort = (reason) =>
      reject(new Error('sherpa-onnx-wasm aborted: ' + reason));
  });

  const asrHelperSrc = await (await fetch(asrHelperUrl)).text();
  (0, eval)(asrHelperSrc); // defines global createOnlineRecognizer/OnlineRecognizer/OnlineStream

  const mainSrc = await (await fetch(mainUrl)).text();
  (0, eval)(mainSrc); // runs createWasm(); -> fetches .wasm and the model-baked .data

  await readyPromise;

  // encoder/decoder/joiner/tokens live in the preloaded .data (virtual
  // FS), not over HTTP. numThreads: 1, not a knob - this build has no
  // USE_PTHREADS (verified: zero 'pthread' matches in the compiled .js).
  const recognizer = createOnlineRecognizer(Module, {
    featConfig: { sampleRate: 16000, featureDim: 80 },
    modelConfig: {
      transducer: {
        encoder: './encoder.onnx',
        decoder: './decoder.onnx',
        joiner: './joiner.onnx',
      },
      paraformer: { encoder: '', decoder: '' },
      zipformer2Ctc: { model: '' },
      nemoCtc: { model: '' },
      toneCtc: { model: '' },
      tokens: './tokens.txt',
      numThreads: 1,
      provider: 'cpu',
      debug: 0,
      modelType: '',
      modelingUnit: '',
      bpeVocab: '',
    },
    decodingMethod: 'greedy_search',
    maxActivePaths: 4,
    enableEndpoint: 1,
    rule1MinTrailingSilence: 2.4,
    rule2MinTrailingSilence: 1.2,
    rule3MinUtteranceLength: 20,
    hotwordsFile: '',
    hotwordsScore: 1.5,
    ctcFstDecoderConfig: { graph: '', maxActive: 3000 },
    ruleFsts: '',
    ruleFars: '',
  });

  return { recognizer, stream: recognizer.createStream() };
})
"""

# Synchronous C++ under the hood, unlike onnxruntime-web's session.run()
# - not async, called directly via run_js (no run_sync).
_STEP = """
(bridge, samples) => {
  const { recognizer, stream } = bridge;
  stream.acceptWaveform(16000, samples);
  while (recognizer.isReady(stream)) {
    recognizer.decode(stream);
  }
  const isEndpoint = recognizer.isEndpoint(stream);
  const result = recognizer.getResult(stream);
  if (isEndpoint) {
    recognizer.reset(stream);
  }
  return { text: result.text, isEndpoint };
}
"""

# Flushes the utterance in progress on stop() - without it, audio spoken
# right before Stop is lost (the endpoint detector needs trailing
# silence to fire, which Stop never provides).
_FLUSH = """
(bridge) => {
  const { recognizer, stream } = bridge;
  stream.inputFinished();
  while (recognizer.isReady(stream)) {
    recognizer.decode(stream);
  }
  return { text: recognizer.getResult(stream).text };
}
"""


class TranscriberKrokoWasm(Node[AudioPayload, ObjectPayload]):
    """Transcribe mono, 16 kHz speech incrementally, chunk by chunk."""

    def __init__(
        self,
        asr_helper_url: str,
        wasm_main_url: str,
        **kwargs,
    ):
        """
        Parameters
        ----------
        asr_helper_url : str
            Absolute URL of sherpa-onnx-wasm's JS glue for the online ASR
            API (``sherpa-onnx-asr.js``): defines ``createOnlineRecognizer``
            and the ``OnlineRecognizer``/``OnlineStream`` classes.
        wasm_main_url : str
            Absolute URL of the compiled Emscripten entry point
            (``sherpa-onnx-wasm-main-asr.js``); its ``.wasm`` and
            ``.data`` (the latter holding the Kroko encoder/decoder/
            joiner/tokens, baked in at build time) must sit next to it.
            See this node's README for how this build is produced.
        kwargs : dict
            Superclass arguments.

        """
        super().__init__(**kwargs)

        self._asr_helper_url = asr_helper_url
        self._wasm_main_url = wasm_main_url

        self._bridge = None
        self._step = None
        self._flush = None
        self._last_end = -1.0

    def warmup(self):  # noqa: D102
        self._bridge = run_sync(
            run_js(_LOAD)(self._asr_helper_url, self._wasm_main_url)
        )
        self._step = run_js(_STEP)
        self._flush = run_js(_FLUSH)

        self.logger.info('kroko streaming asr model loaded')

    def update(self, message: Message[AudioPayload], **kwargs):  # noqa: D102
        payload = message.payload

        if payload.sampling_rate != SAMPLING_RATE or payload.channels > 1:
            raise ValueError(
                f'{self.name} needs mono audio at {SAMPLING_RATE} Hz, got '
                f'{payload.channels} channel(s) at {payload.sampling_rate} Hz'
            )

        started = time.perf_counter()

        samples = np.ascontiguousarray(
            payload.audio.astype(np.float32, copy=False)
        )
        result = self._step(self._bridge, to_js(samples))
        self._last_end = payload.end

        text = str(result.text).strip()

        if not text:
            return

        out = Message[ObjectPayload](
            creator=self.name,
            payload=ObjectPayload(
                text=text, start=payload.start, end=payload.end
            ),
        )
        out.meta.update(message.meta)
        out.meta['final'] = bool(result.isEndpoint)
        out.meta['ms_transcribe'] = round(
            (time.perf_counter() - started) * 1000, 1
        )

        self.transmit(out)

    def stop(self):  # noqa: D102
        if self._bridge is not None and self._flush is not None:
            result = self._flush(self._bridge)
            text = str(result.text).strip()

            if text:
                out = Message[ObjectPayload](
                    creator=self.name,
                    payload=ObjectPayload(
                        text=text, start=self._last_end, end=self._last_end
                    ),
                )
                out.meta['final'] = True
                self.transmit(out)

        super().stop()
