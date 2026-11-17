#!/usr/bin/env bash
#
# Boot a StemDeck backend for the score view's browser tests, against a
# throwaway jobs directory holding one track whose piano is already
# transcribed (seed.py). Same isolation as tests/e2e/serve.sh: nothing here can
# touch a developer's real library.

set -euo pipefail

# --no-sync: a plain `uv run` re-syncs the venv to uv.lock, which swaps a CUDA
# torch installed for the GPU (docs/partitura.md) back to the CPU build.

PORT="${1:-8124}"
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="${STEMDECK_SCORE_E2E_DIR:-${TMPDIR:-/tmp}/stemdeck-score-e2e}"

rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR/jobs" "$WORK_DIR/data"

uv run --no-sync python "${REPO_ROOT}/tests/score-e2e/seed.py" "$WORK_DIR/jobs" >/dev/null

cd "$REPO_ROOT"
exec env \
    STEMDECK_JOBS_DIR="$WORK_DIR/jobs" \
    STEMDECK_DATA_DIR="$WORK_DIR/data" \
    STEMDECK_CACHE_DIR="$WORK_DIR/data/cache" \
    STEMDECK_LOGS_DIR="$WORK_DIR/data/logs" \
    STEMDECK_MODELS_DIR="$WORK_DIR/data/models" \
    STEMDECK_DOWNLOADS_DIR="$WORK_DIR/data/downloads" \
    STEMDECK_ACOUSTID_CHECK_KEY=0 \
    STEMDECK_DISCOGS_CHECK_TOKEN=0 \
    STEMDECK_SWAM_OFF="${STEMDECK_SWAM_OFF:-1}" \
    uv run --no-sync uvicorn app.main:app \
        --host 127.0.0.1 \
        --port "$PORT" \
        --log-level warning \
        --timeout-graceful-shutdown 2
