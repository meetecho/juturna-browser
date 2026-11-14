// Where the demos read the transformers.js models from: Hugging Face, at the
// commits the nodes' assets.toml pin, or vendor/ with `?models=vendor` in the
// page URL (after `build/vendor.py`, for working offline).
const REVISIONS = {
  'Xenova/whisper-base': '64da57285918e20ea79ea5c88eed7197933abaa8',
  'Xenova/opus-mt-en-de': '1ca130c44c4c5441ef16d48aae521a424ab644f7',
  'Xenova/opus-mt-en-es': '4b002a4c7edd54a7ced58877258b87f7efd3f892',
  'Xenova/opus-mt-en-fr': '28726206f80896b90035bd99cccd5cc1e151f916',
  'Xenova/opus-mt-en-it': '075406e3c8c2c30634d4a1bd8f00c21d9e162011',
  'Xenova/opus-mt-en-zh': '046f55aec303cdee3e0318604406d4df20f1e8ea',
};

export function models(node, modelId) {
  if (new URLSearchParams(location.search).get('models') === 'vendor') {
    return { models_url: new URL(`../vendor/${node}/models/`, import.meta.url).href, model_id: modelId, revision: '' };
  }
  const revision = REVISIONS[modelId];
  if (!revision) throw new Error(`no pinned revision for ${modelId}`);
  return { models_url: 'https://huggingface.co/', model_id: modelId, revision };
}
