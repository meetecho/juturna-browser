"""
TranslateOpus

Proc node translating text with an OPUS-MT (Marian) model, run by
transformers.js (on top of onnxruntime-web) from inside the Pyodide Worker:
the model is a JS/WASM runtime called from Python, not a Python package.

Each source/target language pair is its own model
(`Xenova/opus-mt-<src>-<tgt>`), vendored separately; `model_id` picks which
one this node instance loads. A
message translates independently of the others: there is no state carried
between calls, unlike `denoise_dfn` or `whisper_asr`.
"""

import time

from pyodide.code import run_js
from pyodide.ffi import run_sync

from juturna.components import Message
from juturna.components import Node

from juturna.payloads import ObjectPayload

_LOAD = """
(async (transformersUrl, wasmMjsUrl, wasmBinUrl, modelsUrl, modelId, revision, maxThreads) => {
  const { pipeline, env } = await import(transformersUrl);
  // transformers.js@4.3.0 workaround: the "local" path pre-check never
  // matches an http(s) URL, so the "remote" branch is used instead.
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
  // Made explicit so maxThreads can actually override
  // onnxruntime-web's own min(4, ceil(cores/2)) default.
  const cores = navigator.hardwareConcurrency || 4;
  env.backends.onnx.wasm.numThreads =
    maxThreads ?? Math.min(4, Math.ceil(cores / 2));
  return await pipeline('translation', modelId, {
    dtype: 'q8',
    ...(revision && { revision }),
  });
})
"""

_TRANSLATE = """
(async (mt, text, srcLang, tgtLang) => {
  const out = await mt(text, { src_lang: srcLang, tgt_lang: tgtLang });
  return out[0].translation_text;
})
"""


class TranslateOpus(Node[ObjectPayload, ObjectPayload]):
    """Translate the ``text`` field of a message with a fixed language pair."""

    def __init__(
        self,
        transformers_url: str,
        wasm_mjs_url: str,
        wasm_bin_url: str,
        models_url: str,
        model_id: str = 'Xenova/opus-mt-en-it',
        source_lang: str = 'en',
        target_lang: str = 'it',
        revision: str = '',
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
            ``Xenova/opus-mt-en-it``. Must match ``source_lang``/
            ``target_lang``.
        source_lang : str
            Language code the model translates from.
        target_lang : str
            Language code the model translates to.
        revision : str
            Commit of the model repository on Hugging Face, with ``models_url``
            set to ``https://huggingface.co/``: the files are read from
            ``<model_id>/resolve/<revision>/``. Empty (default) for a folder
            laid out by ``build/vendor.py``.
        max_threads : int | None
            Cap on onnxruntime-web's WASM thread pool for this node's
            Worker. ``None`` uses the same ``min(4, ceil(cores / 2))`` a
            plain onnxruntime-web default would pick. Worth lowering when
            this node shares a pipeline with ``whisper_asr``: each node
            picks its thread count independently, so two nodes running
            at once can together request more threads than the machine
            has cores.
        kwargs : dict
            Superclass arguments.

        """
        super().__init__(**kwargs)

        self._transformers_url = transformers_url
        self._wasm_mjs_url = wasm_mjs_url
        self._wasm_bin_url = wasm_bin_url
        self._models_url = models_url
        self._model_id = model_id
        self._revision = revision
        self._source_lang = source_lang
        self._target_lang = target_lang
        self._max_threads = max_threads

        self._mt = None
        self._translate = None

    def warmup(self):  # noqa: D102
        self._mt = run_sync(
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
        self._translate = run_js(_TRANSLATE)

        self.logger.info('translation model loaded')

    def update(self, message: Message[ObjectPayload], **kwargs):  # noqa: D102
        # A streaming source (e.g. transcriber_kroko_wasm) marks a partial,
        # not yet final result with meta['final'] = False; translating it
        # would burn a translation call per chunk on text that is about to
        # change. A source that never sets 'final' (e.g. whisper_asr, which
        # transcribes a fixed window whole) is treated as always final.
        if not message.meta.get('final', True):
            return

        source_text = message.payload.get('text')

        if not source_text:
            raise ValueError(f"{self.name} needs a non-empty 'text' field")

        started = time.perf_counter()

        translated = run_sync(
            self._translate(
                self._mt, source_text, self._source_lang, self._target_lang
            )
        )

        out = Message[ObjectPayload](
            creator=self.name,
            payload=ObjectPayload(
                text=translated,
                source_text=source_text,
                source_lang=self._source_lang,
                target_lang=self._target_lang,
            ),
        )
        out.meta.update(message.meta)
        elapsed = time.perf_counter() - started
        out.meta['ms_translate'] = round(elapsed * 1000, 1)

        self.transmit(out)
