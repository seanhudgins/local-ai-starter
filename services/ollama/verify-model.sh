#!/usr/bin/env bash
# Verify every file of a pulled model against the sha256 in its manifest.
# Ollama names each file after its hash, so a match proves the file is exactly what the registry
# published and wasn't corrupted or swapped on disk.
#   bash services/ollama/verify-model.sh <model-tag> [models-dir]     e.g. qwen3.6:27b-mlx
# Default models dir: $OLLAMA_MODELS, else ~/.ollama/models. Works on macOS and in WSL2.
set -u
tag="${1:?usage: verify-model.sh <model-tag> [models-dir]}"
dir="${2:-${OLLAMA_MODELS:-$HOME/.ollama/models}}"

name="${tag%%:*}"; version="${tag#*:}"; [ "$version" = "$tag" ] && version=latest
case "$name" in */*) repo="$name" ;; *) repo="library/$name" ;; esac
manifest="$dir/manifests/registry.ollama.ai/$repo/$version"
[ -f "$manifest" ] || { echo "FAIL  no manifest at $manifest"; exit 1; }

if command -v sha256sum >/dev/null; then hash() { sha256sum "$1" | cut -d' ' -f1; }
else hash() { shasum -a 256 "$1" | cut -d' ' -f1; }; fi

ok=0; bad=0
for digest in $(grep -oE 'sha256:[0-9a-f]{64}' "$manifest" | sort -u); do
    file="$dir/blobs/sha256-${digest#sha256:}"
    if [ -f "$file" ] && [ "sha256:$(hash "$file")" = "$digest" ]; then
        ok=$((ok + 1))
    else
        bad=$((bad + 1)); echo "BAD   $digest"
    fi
done

echo "$tag: $ok file(s) match, $bad don't"
[ "$bad" -eq 0 ] && [ "$ok" -gt 0 ] && echo "PASS  all model files verified" || { echo "FAIL"; exit 1; }
