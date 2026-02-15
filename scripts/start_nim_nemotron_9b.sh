#!/usr/bin/env bash
set -euo pipefail

# Starts a local NVIDIA NIM container for Nemotron Nano 9B.
# Requires:
# - Docker with NVIDIA runtime support
# - NGC_API_KEY in environment
#
# Optional env vars:
# - NIM_IMAGE (default below)
# - NIM_CONTAINER_NAME (default: nim-nemotron-9b)
# - NIM_PORT (default: 8000)
# - NIM_CACHE_DIR (default: $HOME/.cache/nim)
# - NIM_DETACH (default: 0; set to 1 to run detached)
# - NIM_PLATFORM (optional; e.g. linux/arm64 or linux/amd64)

NIM_IMAGE="${NIM_IMAGE:-nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2-dgx-spark:1.0.0-variant}"
NIM_CONTAINER_NAME="${NIM_CONTAINER_NAME:-nim-nemotron-9b}"
NIM_PORT="${NIM_PORT:-8000}"
NIM_CACHE_DIR="${NIM_CACHE_DIR:-$HOME/.cache/nim}"
NIM_DETACH="${NIM_DETACH:-0}"
HOST_ARCH="$(uname -m)"
NIM_PLATFORM="${NIM_PLATFORM:-}"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required but not found." >&2
  exit 1
fi

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "ERROR: nvidia-smi not found; NVIDIA GPU/driver appears unavailable." >&2
  exit 1
fi

if [[ -z "${NGC_API_KEY:-}" ]]; then
  cat >&2 <<'EOF'
ERROR: NGC_API_KEY is not set.
Set it first, for example:
  export NGC_API_KEY=nvapi-...
EOF
  exit 1
fi

if [[ -z "${NIM_PLATFORM}" ]]; then
  if [[ "${HOST_ARCH}" == "aarch64" || "${HOST_ARCH}" == "arm64" ]]; then
    NIM_PLATFORM="linux/arm64"
  elif [[ "${HOST_ARCH}" == "x86_64" || "${HOST_ARCH}" == "amd64" ]]; then
    NIM_PLATFORM="linux/amd64"
  fi
fi

if [[ "${HOST_ARCH}" == "aarch64" || "${HOST_ARCH}" == "arm64" ]]; then
  echo "Detected ARM64 host (${HOST_ARCH})."
  echo "Using platform hint: ${NIM_PLATFORM:-auto}"
fi

if docker ps -a --format '{{.Names}}' | grep -qx "${NIM_CONTAINER_NAME}"; then
  if docker ps --format '{{.Names}}' | grep -qx "${NIM_CONTAINER_NAME}"; then
    echo "Container '${NIM_CONTAINER_NAME}' is already running."
    echo "NIM chat URL: http://127.0.0.1:${NIM_PORT}/v1/chat/completions"
    exit 0
  fi
  docker rm "${NIM_CONTAINER_NAME}" >/dev/null
fi

mkdir -p "${NIM_CACHE_DIR}"

RUN_ARGS=(
  --name "${NIM_CONTAINER_NAME}"
  --gpus all
  -e NGC_API_KEY
  -p "${NIM_PORT}:8000"
  -v "${NIM_CACHE_DIR}:/opt/nim/.cache"
)

if [[ -n "${NIM_PLATFORM}" ]]; then
  RUN_ARGS+=(--platform "${NIM_PLATFORM}")
fi

if [[ "${NIM_DETACH}" == "1" ]]; then
  RUN_ARGS+=(-d)
else
  if [[ -t 0 && -t 1 ]]; then
    RUN_ARGS+=(-it)
  else
    RUN_ARGS+=(-i)
  fi
fi

echo "Starting NIM container '${NIM_CONTAINER_NAME}' from image '${NIM_IMAGE}'..."
docker run --rm "${RUN_ARGS[@]}" "${NIM_IMAGE}"

if [[ "${NIM_DETACH}" == "1" ]]; then
  cat <<EOF
NIM launched in detached mode.
- Chat URL: http://127.0.0.1:${NIM_PORT}/v1/chat/completions
- Model: nvidia/nemotron-nano-9b-v2
- Follow logs: docker logs -f ${NIM_CONTAINER_NAME}
EOF
fi
