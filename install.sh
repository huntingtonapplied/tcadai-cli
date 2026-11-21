#!/usr/bin/env bash
set -euo pipefail

# Install the TCAD AI CLI binary.

BIN_NAME="tcadai"
INSTALL_DIR_DEFAULT="/usr/local/bin"
BASE_URL_DEFAULT="${BOLTZMANN_DOWNLOADS_BASE_URL:-https://downloads.tcadai.com}"

usage() {
  cat <<'EOF'
Usage:
  install.sh [--version <version>] [--base-url <url>] [--install-dir <dir>] [--no-modify-path]

Options:
  --version      Release version to install (e.g. 1.0.0). Defaults to "latest".
  --base-url     Base URL hosting /cli (default: $BOLTZMANN_DOWNLOADS_BASE_URL or https://downloads.tcadai.com)
  --install-dir  Install directory (default: /usr/local/bin)
  --no-modify-path  Do not add the install dir to PATH in your shell rc file

Environment:
  NO_MODIFY_PATH=1  Same as --no-modify-path
  BOLTZMANN_DOWNLOADS_BASE_URL  Overrides default base URL
EOF
}

VERSION="latest"
BASE_URL="$BASE_URL_DEFAULT"
INSTALL_DIR="$INSTALL_DIR_DEFAULT"
case "${NO_MODIFY_PATH:-}" in ""|0|false|no) MODIFY_PATH="1" ;; *) MODIFY_PATH="0" ;; esac

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="${2:-}"; shift 2 ;;
    --base-url)
      BASE_URL="${2:-}"; shift 2 ;;
    --install-dir)
      INSTALL_DIR="${2:-}"; shift 2 ;;
    --no-modify-path)
      MODIFY_PATH="0"; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

uname_s="$(uname -s | tr '[:upper:]' '[:lower:]')"
uname_m="$(uname -m)"

case "$uname_s" in
  darwin) os="darwin" ;;
  linux) os="linux" ;;
  *)
    echo "Unsupported OS: $uname_s" >&2
    exit 1
    ;;
esac

case "$uname_m" in
  x86_64|amd64) arch="x86_64" ;;
  arm64|aarch64) arch="arm64" ;;
  *)
    echo "Unsupported arch: $uname_m" >&2
    exit 1
    ;;
esac

asset="tcadai-${os}-${arch}"
rel_url="${BASE_URL%/}/cli/releases/${VERSION}"
url="${rel_url}/${asset}"
sums_url="${rel_url}/SHA256SUMS"

tmp="$(mktemp -t tcadai-cli.XXXXXX)"
cleanup() { rm -f "$tmp" "$tmp.sums"; }
trap cleanup EXIT

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else echo ""; fi
}

# Read the release's SHA256SUMS first: it lists exactly the binaries that were
# published, so an OS/arch with no build gets a clear message instead of a raw
# curl 404 (BZ CLI-06: Intel macOS and ARM Linux have no binaries yet).
if ! curl -fsSL "$sums_url" -o "$tmp.sums" 2>/dev/null; then
  if [[ "$VERSION" != "latest" ]]; then
    echo "ERROR: TCAD AI CLI release ${VERSION} was not found (no SHA256SUMS at $sums_url)." >&2
    echo "  Check the version, or omit --version to install the latest release." >&2
  else
    echo "ERROR: could not fetch SHA256SUMS at $sums_url; cannot verify this download. Refusing to install." >&2
  fi
  exit 4
fi

available="$(awk 'NF>=2 {f=$2; sub(/^\*/, "", f); sub(/^tcadai-/, "", f); printf "%s%s", sep, f; sep=", "}' "$tmp.sums")"
expected="$(awk -v f="$asset" '$2==f || $2=="*"f {print $1; exit}' "$tmp.sums")"
if [[ -z "$expected" ]]; then
  echo "ERROR: Unsupported platform: there is no prebuilt TCAD AI CLI binary for ${os}-${arch} (${uname_s} ${uname_m}) in release ${VERSION}." >&2
  echo "  Available builds: ${available:-none}" >&2
  echo "  Supported today: Apple Silicon macOS (darwin-arm64) and x86_64 Linux (linux-x86_64)." >&2
  echo "  On other platforms, install from source: clone the repo and run 'pip install -e cli/'." >&2
  exit 3
fi

echo "Downloading: $url"
if ! curl -fsSL "$url" -o "$tmp" 2>/dev/null; then
  echo "ERROR: download failed for $asset from $url (it is listed in SHA256SUMS but could not be fetched)." >&2
  echo "  Check your connection and retry; if it keeps failing the release is incomplete." >&2
  exit 5
fi
chmod 755 "$tmp"

# Integrity: verify against the release's SHA256SUMS.
actual="$(sha256_of "$tmp")"
rm -f "$tmp.sums"
if [[ -z "$actual" ]]; then
  echo "ERROR: no sha256 tool (sha256sum or shasum) available to verify $asset. Refusing to install." >&2
  exit 4
fi
if [[ "$actual" != "$expected" ]]; then
  echo "ERROR: checksum mismatch for $asset (expected $expected, got $actual)" >&2
  exit 4
fi
echo "Verified: sha256 OK"

dest="$INSTALL_DIR/$BIN_NAME"
if [[ ! -d "$INSTALL_DIR" ]]; then
  echo "Creating install dir: $INSTALL_DIR"
  mkdir -p "$INSTALL_DIR"
fi

if [[ -w "$INSTALL_DIR" ]]; then
  mv "$tmp" "$dest"
else
  echo "Installing to $dest (requires sudo)"
  sudo mv "$tmp" "$dest"
fi

echo "Installed: $dest"
if [[ "$BIN_NAME" == "tcadai" && ! -e "$INSTALL_DIR/boltzmann" ]]; then
  ln -s "$dest" "$INSTALL_DIR/boltzmann" 2>/dev/null || true
fi
"$dest" --help >/dev/null

# Add the install dir to PATH if it is not there already (HQ2 INSTALLSH-BASHRC).
# Rules: never fail after a good install; only touch an rc file that already exists;
# never write the same line twice; opt out with --no-modify-path or NO_MODIFY_PATH=1.
if [[ ":${PATH:-}:" != *":$INSTALL_DIR:"* ]]; then
  path_line="export PATH=\"$INSTALL_DIR:\$PATH\""
  shell_rc="${HOME:-}/.bashrc"
  if [[ -n "${ZSH_VERSION:-}" ]] || [[ "${SHELL:-}" == */zsh ]]; then
    shell_rc="${HOME:-}/.zshrc"
  fi
  path_hint() {
    echo "$INSTALL_DIR is not in your PATH. To add it, run:"
    echo "  echo '$path_line' >> $shell_rc"
  }

  if [[ "$MODIFY_PATH" != "1" ]]; then
    path_hint
  elif [[ -z "${HOME:-}" || ! -f "$shell_rc" ]]; then
    echo "Not modifying PATH: $shell_rc does not exist."
    path_hint
  elif grep -qxF "$path_line" "$shell_rc" 2>/dev/null; then
    echo "$INSTALL_DIR is already on PATH in $shell_rc (open a new shell or run: source $shell_rc)"
  else
    add_path="Y"
    if [[ -t 0 ]]; then
      read -r -p "Add $INSTALL_DIR to PATH in $shell_rc? [Y/n] " add_path || add_path="n"
    fi
    if [[ "${add_path:-Y}" =~ ^[Yy] ]]; then
      if { echo ""; echo "$path_line"; } >> "$shell_rc" 2>/dev/null; then
        echo "Added $INSTALL_DIR to PATH in $shell_rc (open a new shell or run: source $shell_rc)"
        echo "  (skip this next time with --no-modify-path or NO_MODIFY_PATH=1)"
      else
        echo "Could not write $shell_rc."
        path_hint
      fi
    else
      path_hint
    fi
  fi
fi

echo "OK"
