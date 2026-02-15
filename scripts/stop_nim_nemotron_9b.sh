#!/usr/bin/env bash
set -euo pipefail

NIM_CONTAINER_NAME="${NIM_CONTAINER_NAME:-nim-nemotron-9b}"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required but not found." >&2
  exit 1
fi

if docker ps --format '{{.Names}}' | grep -qx "${NIM_CONTAINER_NAME}"; then
  docker stop "${NIM_CONTAINER_NAME}" >/dev/null
  echo "Stopped ${NIM_CONTAINER_NAME}."
  exit 0
fi

if docker ps -a --format '{{.Names}}' | grep -qx "${NIM_CONTAINER_NAME}"; then
  docker rm "${NIM_CONTAINER_NAME}" >/dev/null
  echo "Removed stopped container ${NIM_CONTAINER_NAME}."
  exit 0
fi

echo "Container ${NIM_CONTAINER_NAME} not found."
