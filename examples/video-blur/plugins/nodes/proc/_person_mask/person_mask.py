"""
PersonMask

Proc node segmenting the person in a video frame with a portrait segmentation
model run by onnxruntime-web, from inside the Pyodide Worker: the model is a
JS/WASM runtime called from Python, not a Python package.

The mask is written in the alpha channel of the frame: a message carries a
single array, and a camera frame has no use for its alpha.
"""

import time

import numpy as np

from juturna.components import Message
from juturna.components import Node

from juturna.payloads import ImagePayload

_LOAD = """
(async (ortUrl, wasmPath, modelUrl, maxThreads) => {
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
  return { ort, session };
})
"""

# the model takes uint8 RGB as [1, height, width, 3] and returns the alpha
# matte as float32 [1, height, width, 1]. The RGBA frame is split here: doing
# it on the numpy side costs a strided copy on top of the one to_js makes.
_INFER = """
(async ({ ort, session }, rgba, height, width) => {
  const pixels = height * width;
  const rgb = new Uint8Array(pixels * 3);
  for (let i = 0, j = 0; i < pixels * 4; i += 4, j += 3) {
    rgb[j] = rgba[i];
    rgb[j + 1] = rgba[i + 1];
    rgb[j + 2] = rgba[i + 2];
  }
  const input = new ort.Tensor('uint8', rgb, [1, height, width, 3]);
  const output = await session.run({ pixel_values: input });
  return output.alphas.data;
})
"""


class PersonMask(Node[ImagePayload, ImagePayload]):
    """Put the person mask of an RGBA frame in its alpha channel."""

    def __init__(
        self,
        ort_url: str,
        wasm_path: str,
        model_url: str,
        max_threads: int | None = None,
        **kwargs,
    ):
        """
        Parameters
        ----------
        ort_url : str
            Absolute URL of the onnxruntime-web ES module (``ort.wasm.min.mjs``).
        wasm_path : str
            Absolute URL of the folder with the onnxruntime-web WASM files.
        model_url : str
            Absolute URL of the segmentation model.
        max_threads : int | None
            Cap on onnxruntime-web's WASM thread pool for this node's
            Worker. ``None`` or 0 uses the same ``min(4, ceil(cores / 2))``
            onnxruntime-web would pick on its own.
        kwargs : dict
            Superclass arguments.

        """
        super().__init__(**kwargs)

        self._ort_url = ort_url
        self._wasm_path = wasm_path
        self._model_url = model_url
        # config.toml cannot hold None: its default, 0, stands for it
        self._max_threads = max_threads or None

        self._runtime = None
        self._infer = None

    def warmup(self):  # noqa: D102
        from pyodide.code import run_js
        from pyodide.ffi import run_sync

        self._runtime = run_sync(
            run_js(_LOAD)(
                self._ort_url,
                self._wasm_path,
                self._model_url,
                self._max_threads,
            )
        )
        self._infer = run_js(_INFER)

        self.logger.info('segmentation model loaded')

    def update(self, message: Message[ImagePayload], **kwargs):  # noqa: D102
        from pyodide.ffi import run_sync
        from pyodide.ffi import to_js

        started = time.perf_counter()

        frame = message.payload.image
        height, width = frame.shape[:2]

        alphas = run_sync(
            self._infer(
                self._runtime,
                to_js(np.ascontiguousarray(frame).reshape(-1)),
                height,
                width,
            )
        )
        mask = np.array(alphas.to_py(), dtype=np.float32).reshape(height, width)

        out = frame.copy()
        out[..., 3] = (np.clip(mask, 0.0, 1.0) * 255).astype(np.uint8)

        result = Message[ImagePayload](
            creator=self.name,
            payload=ImagePayload(
                image=out,
                width=width,
                height=height,
                depth=4,
                pixel_format='rgba',
                timestamp=message.payload.timestamp,
            ),
        )
        result.meta.update(message.meta)
        result.meta['ms_segment'] = round(
            (time.perf_counter() - started) * 1000, 1
        )

        self.transmit(result)
