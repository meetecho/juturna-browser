"""
Test node: measures the cost of a single run_sync() call that internally
awaits N times in sequence, from inside Node.update() (i.e. from inside the
coroutine BrowserTransport.spawn() creates for Node._update()). N is read
from the input message, not from the node config, so one node instance can
be probed for many values of N without rebuilding the pipeline.

Two modes:
- "synthetic" (default): N awaits on a bare Promise (setTimeout(0)), no
  computation. First version of this probe - see design/CLAUDE.md ("Limite
  JSPI: molti await in sequenza dentro una run_sync") for what it found and
  why that finding was retracted: it does not reproduce inside a real
  dedicated Worker, only on the page's own Pyodide instance.
- "onnx": N real onnxruntime-web session.run() calls in sequence, on the
  tiny selfie-segmentation model already vendored for person_mask (a real
  inference, not a proxy) - the model expects uint8 RGB
  [1, height, width, 3], and `size` picks a small height/width to keep each
  call cheap. Needs `ort_url`/`wasm_mjs_url`/`wasm_bin_url`/`model_url`
  pointing at vendor/person_mask/... (see examples/video-blur's assets.toml)
  and `num_threads` to test whether onnxruntime-web's own thread pool,
  spawned again for every model load, is what degrades inside a Worker.
"""

import time

import numpy as np

from juturna.components import Message
from juturna.components import Node

from juturna.payloads import ObjectPayload

# awaits a real Promise N times in sequence, inside one JS async function -
# the same shape as transformers.js's pipeline() awaiting one session.run()
# per generated token, just with no computation behind each await
_MANY_AWAITS = """
(async (n) => {
  for (let i = 0; i < n; i++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  return n;
})
"""

_LOAD_ONNX = """
(async (ortUrl, wasmMjsUrl, wasmBinUrl, modelUrl, numThreads) => {
  const ort = await import(ortUrl);
  ort.env.wasm.wasmPaths = { mjs: wasmMjsUrl, wasm: wasmBinUrl };
  ort.env.wasm.numThreads = numThreads;
  const bytes = new Uint8Array(await (await fetch(modelUrl)).arrayBuffer());
  return await ort.InferenceSession.create(bytes, {
    executionProviders: ['wasm'],
  });
})
"""

# N real session.run() calls in sequence, inside one JS async function - the
# same shape _LOAD_ONNX's caller uses for Whisper's decode loop, just on a
# tiny model instead of transformers.js's generation loop
_MANY_INFERENCES = """
(async (session, ort, rgb, size, n) => {
  const input = new ort.Tensor('uint8', rgb, [1, size, size, 3]);
  for (let i = 0; i < n; i++) {
    await session.run({ pixel_values: input });
  }
  return n;
})
"""


class AwaitProbe(Node[ObjectPayload, ObjectPayload]):
    """Time N sequential awaits in one run_sync(), synthetic or real ONNX."""

    def __init__(
        self,
        mode: str = 'synthetic',
        ort_url: str = '',
        wasm_mjs_url: str = '',
        wasm_bin_url: str = '',
        model_url: str = '',
        num_threads: int = 4,
        size: int = 32,
        **kwargs,
    ):
        """
        Parameters
        ----------
        mode : str
            ``synthetic`` (N bare awaits) or ``onnx`` (N real
            ``session.run()`` calls on a tiny vendored model).
        ort_url, wasm_mjs_url, wasm_bin_url, model_url : str
            Only for ``mode="onnx"``: same arguments as ``person_mask``.
        num_threads : int
            Only for ``mode="onnx"``: ``onnxruntime-web``'s own thread pool
            size, to test whether nested Worker threads are what degrades.
        size : int
            Only for ``mode="onnx"``: height/width of the dummy RGB frame.
        kwargs : dict
            Superclass arguments.

        """
        super().__init__(**kwargs)

        self._mode = mode
        self._ort_url = ort_url
        self._wasm_mjs_url = wasm_mjs_url
        self._wasm_bin_url = wasm_bin_url
        self._model_url = model_url
        self._num_threads = num_threads
        self._size = size

        self._call = None
        self._session = None
        self._ort = None
        self._rgb = None

    def warmup(self):  # noqa: D102
        from pyodide.code import run_js
        from pyodide.ffi import run_sync
        from pyodide.ffi import to_js

        if self._mode == 'synthetic':
            self._call = run_js(_MANY_AWAITS)
            return

        loaded = run_sync(
            run_js(_LOAD_ONNX)(
                self._ort_url,
                self._wasm_mjs_url,
                self._wasm_bin_url,
                self._model_url,
                self._num_threads,
            )
        )
        # the module namespace (for its Tensor class) and the session are
        # both needed at inference time, and re-importing the module is
        # free (the browser's module cache returns the same instance)
        self._session = loaded
        self._ort = run_sync(run_js(f'import("{self._ort_url}")'))
        rgb = np.zeros((self._size, self._size, 3), dtype=np.uint8).reshape(-1)
        self._rgb = to_js(rgb)
        self._call = run_js(_MANY_INFERENCES)

    def update(self, message: Message[ObjectPayload], **kwargs):  # noqa: D102
        from pyodide.ffi import run_sync

        n = message.payload['n']

        started = time.perf_counter()

        if self._mode == 'synthetic':
            run_sync(self._call(n))
        else:
            run_sync(
                self._call(self._session, self._ort, self._rgb, self._size, n)
            )

        elapsed = time.perf_counter() - started

        out = Message[ObjectPayload](
            creator=self.name,
            payload=ObjectPayload(n=n, elapsed_s=round(elapsed, 3)),
        )
        out.meta.update(message.meta)

        self.transmit(out)
