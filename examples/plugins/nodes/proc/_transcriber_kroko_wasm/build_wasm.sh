#!/usr/bin/env bash
# Reproduces the sherpa-onnx-wasm ASR build this node loads at runtime
# (`sherpa-onnx-asr.js` + `sherpa-onnx-wasm-main-asr.{js,wasm,data}`), with
# Kroko's streaming Zipformer (en, 2025-08-06) baked in.
#
# Unlike this project's other JS/WASM dependencies (onnxruntime-web,
# transformers.js, the person_mask/denoise_dfn ONNX models), sherpa-onnx-wasm
# is not something `build/vendor.py` can fetch: the model is compiled INTO
# the .wasm/.data at build time (Emscripten `--preload-file`), so there is
# no single stable URL to point an `assets.toml` `[[asset]]` at - the
# artifact is unique to (model, sherpa-onnx version) and has to be produced
# locally. Run this script once, then point `vendor.py`'s destination or a
# demo page's config at the files it prints at the end (see this directory's
# README, "Vendoring these files").
#
# Prerequisites: git, cmake, ~2 GB free disk, and Emscripten - NOT already
# installed by this project's usual `pip install`/`npm install`; get it with:
#   git clone https://github.com/emscripten-core/emsdk.git
#   cd emsdk && ./emsdk install latest && ./emsdk activate latest
#   source ./emsdk_env.sh
# (the sherpa-onnx build script itself pins no version; 6.0.10, "latest" as
# of 2026-09, is what this was last built and verified with - sherpa-onnx's
# own docs mention 4.0.23 as "known to work" if 6.0.10 ever regresses).
#
# Usage (from anywhere, after `source emsdk_env.sh` in the same shell):
#   ./build_wasm.sh [-m|--model MODEL_URL] [-wd|--workdir WORKDIR]
# MODEL_URL specifies the URL from which to download the model files (encoder.onnx, decoder.onnx, joiner.onnx, tokens.txt).
# WORKDIR defaults to a temporary directory; the source clones and the
# multi-GB build tree live there, not in this repo.
#
# Example:
#   ./build_wasm.sh -m https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06/resolve/572aaf4e2e0c603c3fc2a574d096e755a178faa1 -wd /tmp/kroko-build
#
# Both sources are fixed, so that two builds give the same files: the tag of
# sherpa-onnx (the latest one when the build was last verified, 2026-09) and
# the revision of the model repository.

set -euo pipefail

SHERPA_ONNX_TAG='v1.13.8'
MODEL_URL='https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06/resolve/572aaf4e2e0c603c3fc2a574d096e755a178faa1'

if ! command -v emcc &> /dev/null; then
  echo 'emcc not found - source emsdk_env.sh first (see the comment above).' >&2
  exit 1
fi

while [ $# -gt 0 ]; do
  case "$1" in
    -m | --model)
      MODEL_URL="$2"
      shift
      ;;
    -wd | --workdir)
      WORKDIR="$2"
      shift
      ;;
    -h | --help)
      echo "Usage: $0 [-m|--model MODEL_URL] [-wd|--workdir WORKDIR]"
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      WORKDIR="$1"
      ;;
  esac
  shift
done

WORKDIR="${WORKDIR:-$(mktemp -d -t kroko-wasm-build-XXXXXX)}"

mkdir -p "$WORKDIR"
echo "building in $WORKDIR"

if [ ! -d "$WORKDIR/sherpa-onnx" ]; then
  git clone --depth 1 --branch "$SHERPA_ONNX_TAG" https://github.com/k2-fsa/sherpa-onnx.git "$WORKDIR/sherpa-onnx"
fi

# a checkout left there by an earlier build would be built as it is
if [ "$(git -C "$WORKDIR/sherpa-onnx" describe --tags --exact-match 2> /dev/null)" != "$SHERPA_ONNX_TAG" ]; then
  echo "$WORKDIR/sherpa-onnx is not at $SHERPA_ONNX_TAG: remove it, or use another WORKDIR" >&2
  exit 1
fi

cd "$WORKDIR/sherpa-onnx/wasm/asr/assets"
for f in encoder.onnx decoder.onnx joiner.onnx tokens.txt; do
  [ -f "$f" ] || curl -fsL -o "$f" "$MODEL_URL/$f"
done

cd "$WORKDIR/sherpa-onnx"
./build-wasm-simd-asr.sh

OUT="$WORKDIR/sherpa-onnx/build-wasm-simd-asr/install/bin/wasm/asr"
echo
echo "done. vendor these 4 files together (they must sit next to each other):"
ls -lh \
  "$WORKDIR/sherpa-onnx/wasm/asr/sherpa-onnx-asr.js" \
  "$OUT/sherpa-onnx-wasm-main-asr.js" \
  "$OUT/sherpa-onnx-wasm-main-asr.wasm" \
  "$OUT/sherpa-onnx-wasm-main-asr.data"
