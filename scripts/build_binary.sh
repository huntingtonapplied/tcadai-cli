#!/usr/bin/env bash
set -euo pipefail

# Build a standalone 'boltzmann' binary with PyInstaller.
# Intended for both local use and SEGA/GitHub CI runners.

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv-build}"
NAME="${NAME:-tcadai}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -U pip
"$VENV_DIR/bin/pip" install -e .
"$VENV_DIR/bin/pip" install -U pyinstaller

# Stamp the source commit into the binary (R1103-BINARY-CLI-NO-COMMIT-STALE-MANIFEST). BOLTZMANN_BUILD_ID wins,
# else this checkout's HEAD. The committed placeholder is restored afterwards.
BUILD_INFO="tcadai_cli/_build_info.py"
COMMIT="${BOLTZMANN_BUILD_ID:-$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || true)}"
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo "Cannot stamp build: set BOLTZMANN_BUILD_ID to a full 40-hex sha" >&2; exit 1; }
restore_build_info() { sed -i.bak -E 's/^COMMIT = "[0-9a-f]*"/COMMIT = ""/' "$BUILD_INFO" && rm -f "$BUILD_INFO.bak"; }
trap restore_build_info EXIT
sed -i.bak -E "s/^COMMIT = \"[0-9a-f]*\"/COMMIT = \"$COMMIT\"/" "$BUILD_INFO" && rm -f "$BUILD_INFO.bak"
grep -q "^COMMIT = \"$COMMIT\"" "$BUILD_INFO" || { echo "stamp failed" >&2; exit 1; }

"$VENV_DIR/bin/pyinstaller" --onefile --name "$NAME" tcadai_cli/main.py

if [[ ! -f "dist/$NAME" ]]; then
  echo "Expected dist/$NAME to exist" >&2
  exit 1
fi

"dist/$NAME" --help >/dev/null
"dist/$NAME" --version | grep -q "commit ${COMMIT:0:12}" || { echo "built binary does not report commit ${COMMIT:0:12}" >&2; exit 1; }
echo "Built dist/$NAME"
