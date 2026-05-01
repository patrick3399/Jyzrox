#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
PWA_DIR="$ROOT_DIR/pwa"

RUN_BACKEND=1
RUN_FRONTEND=1
RUN_BACKEND_TYPECHECK=0
RUN_DOCKER_SMOKE=0
RUN_FULL_LINT=0
SKIP_BUILD=0

usage() {
  cat <<'EOF'
Usage: scripts/local-ci.sh [options]

Runs the local quality gate used before longer Jyzrox tasks.

Options:
  --backend-only          Run backend checks only.
  --frontend-only         Run frontend checks only.
  --typecheck-backend     Also run backend Pyright if available.
  --full-lint             Lint all backend/frontend files instead of changed files.
  --docker-smoke          Also run Docker Compose smoke checks.
  --skip-build            Skip the frontend production build.
  -h, --help              Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-only)
      RUN_FRONTEND=0
      ;;
    --frontend-only)
      RUN_BACKEND=0
      ;;
    --typecheck-backend)
      RUN_BACKEND_TYPECHECK=1
      ;;
    --full-lint)
      RUN_FULL_LINT=1
      ;;
    --docker-smoke)
      RUN_DOCKER_SMOKE=1
      ;;
    --skip-build)
      SKIP_BUILD=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

section() {
  printf '\n==> %s\n' "$1"
}

run() {
  printf '+ %s\n' "$*"
  "$@"
}

changed_files() {
  local base_ref
  if git -C "$ROOT_DIR" rev-parse --verify origin/dev >/dev/null 2>&1; then
    base_ref="origin/dev"
  elif git -C "$ROOT_DIR" rev-parse --verify origin/main >/dev/null 2>&1; then
    base_ref="origin/main"
  else
    base_ref="HEAD"
  fi

  {
    git -C "$ROOT_DIR" diff --name-only --diff-filter=ACMR "$base_ref"...HEAD
    git -C "$ROOT_DIR" diff --name-only --diff-filter=ACMR
    git -C "$ROOT_DIR" diff --cached --name-only --diff-filter=ACMR
    git -C "$ROOT_DIR" ls-files --others --exclude-standard
  } | sort -u
}

ensure_backend_venv() {
  if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]]; then
    section "Create backend virtual environment"
    run python3 -m venv "$BACKEND_DIR/.venv"
    run "$BACKEND_DIR/.venv/bin/python" -m pip install --upgrade pip
    run "$BACKEND_DIR/.venv/bin/python" -m pip install -r "$BACKEND_DIR/requirements-dev.txt"
  fi
}

run_backend_checks() {
  ensure_backend_venv

  mapfile -t backend_changed < <(changed_files | awk '/^backend\/.*\.py$/ { sub("^backend/", ""); print }')
  if [[ "$RUN_FULL_LINT" -eq 1 ]]; then
    section "Backend ruff check"
    (cd "$BACKEND_DIR" && run .venv/bin/ruff check .)

    section "Backend ruff format check"
    (cd "$BACKEND_DIR" && run .venv/bin/ruff format --check .)
  elif [[ "${#backend_changed[@]}" -gt 0 ]]; then
    section "Backend ruff check changed files"
    (cd "$BACKEND_DIR" && run .venv/bin/ruff check "${backend_changed[@]}")

    section "Backend ruff format check changed files"
    (cd "$BACKEND_DIR" && run .venv/bin/ruff format --check "${backend_changed[@]}")
  else
    section "Backend ruff"
    echo "No changed backend Python files; skipping changed-file lint."
  fi

  if [[ "$RUN_BACKEND_TYPECHECK" -eq 1 ]]; then
    section "Backend Pyright"
    if command -v pyright >/dev/null 2>&1; then
      (cd "$BACKEND_DIR" && run pyright)
    elif command -v npx >/dev/null 2>&1; then
      (cd "$BACKEND_DIR" && run npx --yes pyright)
    else
      echo "Pyright skipped: neither pyright nor npx is available." >&2
    fi
  fi

  section "Backend pytest"
  (cd "$BACKEND_DIR" && run .venv/bin/pytest)
}

run_frontend_checks() {
  if [[ ! -d "$PWA_DIR/node_modules" ]]; then
    section "Install frontend dependencies"
    (cd "$PWA_DIR" && run npm install)
  fi

  mapfile -t frontend_changed < <(changed_files | awk '/^pwa\/src\/.*\.(ts|tsx|js|jsx)$/ { sub("^pwa/", ""); print }')
  if [[ "$RUN_FULL_LINT" -eq 1 ]]; then
    section "Frontend lint"
    (cd "$PWA_DIR" && run npm run lint)
  elif [[ "${#frontend_changed[@]}" -gt 0 ]]; then
    section "Frontend eslint changed files"
    (cd "$PWA_DIR" && run npx eslint "${frontend_changed[@]}")
  else
    section "Frontend eslint"
    echo "No changed frontend source files; skipping changed-file lint."
  fi

  section "Frontend type-check"
  (cd "$PWA_DIR" && run npm run type-check)

  section "Frontend tests"
  (cd "$PWA_DIR" && run npm run test)

  if [[ "$SKIP_BUILD" -eq 0 ]]; then
    section "Frontend build"
    (cd "$PWA_DIR" && run npm run build)
  fi
}

run_docker_smoke() {
  section "Docker Compose config"
  (cd "$ROOT_DIR" && run docker compose config --quiet)

  section "Nginx config smoke"
  if docker compose ps --services --filter status=running | grep -qx nginx; then
    (cd "$ROOT_DIR" && run docker compose exec -T nginx nginx -t)
  else
    echo "Nginx smoke skipped: nginx container is not running."
  fi

  section "Worker network smoke"
  if docker compose ps --services --filter status=running | grep -qx worker; then
    (cd "$ROOT_DIR" && run docker compose exec -T worker getent hosts github.com)
    (cd "$ROOT_DIR" && run docker compose exec -T worker python -c "import socket; print(socket.gethostbyname('github.com'))")
  else
    echo "Worker network smoke skipped: worker container is not running."
  fi
}

main() {
  if [[ "$RUN_BACKEND" -eq 1 ]]; then
    run_backend_checks
  fi
  if [[ "$RUN_FRONTEND" -eq 1 ]]; then
    run_frontend_checks
  fi
  if [[ "$RUN_DOCKER_SMOKE" -eq 1 ]]; then
    run_docker_smoke
  fi

  section "Local CI passed"
}

main "$@"
