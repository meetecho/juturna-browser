"""
DenoiseDFN

Proc node removing the noise from speech with DeepFilterNet3, a streaming ONNX
graph run by onnxruntime-web from inside the Pyodide Worker: the model is a
JS/WASM runtime called from Python, not a Python package.

The graph takes 480 samples at 48 kHz (10 ms) and the state of the previous
call, and returns the same amount of cleaned audio and the new state. The
state stays in JS, next to the session: it is 45304 floats, and no reason to
cross into Python 100 times a second.
"""

import time

import numpy as np

from juturna.components import Message
from juturna.components import Node

from juturna.payloads import AudioPayload

SAMPLING_RATE = 48000
FRAME = 480
STATE_SIZE = 45304

_LOAD = """
(async (ortUrl, wasmPath, modelUrl, stateSize, attenuation, maxThreads) => {
  const ort = await import(ortUrl);
  ort.env.wasm.wasmPaths = wasmPath;
  // Made explicit so maxThreads can actually override
  // onnxruntime-web's own min(4, ceil(cores/2)) default.
  const cores = navigator.hardwareConcurrency || 4;
  ort.env.wasm.numThreads = maxThreads ?? Math.min(4, Math.ceil(cores / 2));
  // juturna-browser keeps these files between visits; elsewhere, plain fetch
  const get = self.juturnaFetch ?? fetch;
  const bytes = async (url) => {
    const resp = await get(url);
    if (!resp.ok) throw new Error(`${url}: HTTP ${resp.status}`);
    return resp.arrayBuffer();
  };
  // the runtime too, handed over instead of fetched by ORT on its own
  const runtime = new URL('ort-wasm-simd-threaded.wasm', wasmPath).href;
  ort.env.wasm.wasmBinary = await bytes(runtime);
  const model = new Uint8Array(await bytes(modelUrl));
  const session = await ort.InferenceSession.create(model, {
    executionProviders: ['wasm'],
  });
  return {
    ort, session, states: new Float32Array(stateSize),
    attenuation: new ort.Tensor('float32', new Float32Array([attenuation]), []),
  };
})
"""

# every complete frame of `samples`, one after the other: each call gets the
# state the previous one returned
_DENOISE = """
(async (runtime, samples) => {
  const { ort, session, attenuation } = runtime;
  const STATE_SIZE = runtime.states.length;
  const frames = samples.length / 480;
  const out = new Float32Array(samples.length);
  let lsnr = 0;

  for (let i = 0; i < frames; i++) {
    const frame = samples.subarray(i * 480, (i + 1) * 480);
    const result = await session.run({
      input_frame: new ort.Tensor('float32', frame, [480]),
      states: new ort.Tensor('float32', runtime.states, [STATE_SIZE]),
      atten_lim_db: attenuation,
    });
    out.set(result.enhanced_audio_frame.data, i * 480);
    runtime.states = result.new_states.data;
    lsnr += result.lsnr.data[0];
  }
  return { audio: out, lsnr: frames ? lsnr / frames : 0 };
})
"""


class DenoiseDFN(Node[AudioPayload, AudioPayload]):
    """Remove the noise from a mono, 48 kHz audio stream."""

    def __init__(
        self,
        ort_url: str,
        wasm_path: str,
        model_url: str,
        attenuation_db: float = 100.0,
        max_threads: int | None = None,
        **kwargs,
    ):
        """
        Parameters
        ----------
        ort_url : str
            Absolute URL of the onnxruntime-web module (``ort.wasm.min.mjs``).
        wasm_path : str
            Absolute URL of the folder with the onnxruntime-web WASM files.
        model_url : str
            Absolute URL of the DeepFilterNet3 streaming model.
        attenuation_db : float
            The most the noise is attenuated, in dB: 100 leaves it to the model,
            a lower value lets some of it through.
        max_threads : int | None
            Cap on onnxruntime-web's WASM thread pool for this node's
            Worker. ``None`` uses the same ``min(4, ceil(cores / 2))``
            onnxruntime-web would pick on its own.
        kwargs : dict
            Superclass arguments.

        """
        super().__init__(**kwargs)

        self._ort_url = ort_url
        self._wasm_path = wasm_path
        self._model_url = model_url
        self._attenuation_db = attenuation_db
        self._max_threads = max_threads

        self._runtime = None
        self._denoise = None
        self._pending = np.zeros(0, dtype=np.float32)

    def warmup(self):  # noqa: D102
        from pyodide.code import run_js
        from pyodide.ffi import run_sync

        self._runtime = run_sync(
            run_js(_LOAD)(
                self._ort_url,
                self._wasm_path,
                self._model_url,
                STATE_SIZE,
                self._attenuation_db,
                self._max_threads,
            )
        )
        self._denoise = run_js(_DENOISE)

        self.logger.info('denoising model loaded')

    def update(self, message: Message[AudioPayload], **kwargs):  # noqa: D102
        from pyodide.ffi import run_sync
        from pyodide.ffi import to_js

        payload = message.payload

        if payload.sampling_rate != SAMPLING_RATE or payload.channels > 1:
            raise ValueError(
                f'{self.name} needs mono audio at {SAMPLING_RATE} Hz, got '
                f'{payload.channels} channel(s) at {payload.sampling_rate} Hz'
            )

        started = time.perf_counter()

        held = len(self._pending)
        samples = np.concatenate(
            [self._pending, payload.audio.astype(np.float32, copy=False)]
        )
        usable = len(samples) // FRAME * FRAME
        self._pending = samples[usable:]

        if not usable:
            return

        result = run_sync(
            self._denoise(
                self._runtime, to_js(np.ascontiguousarray(samples[:usable]))
            )
        )
        audio = np.array(result.audio.to_py(), dtype=np.float32)

        # the first cleaned sample is the oldest one held, not the first one of
        # the message: the times shift by what was held back
        start = payload.start - held / SAMPLING_RATE
        out = Message[AudioPayload](
            creator=self.name,
            payload=AudioPayload(
                audio=audio,
                sampling_rate=SAMPLING_RATE,
                audio_format=payload.audio_format,
                channels=1,
                start=start,
                end=start + usable / SAMPLING_RATE,
            ),
        )
        out.meta.update(message.meta)
        out.meta['lsnr'] = round(float(result.lsnr), 2)
        out.meta['ms_denoise'] = round(
            (time.perf_counter() - started) * 1000, 1
        )

        self.transmit(out)
