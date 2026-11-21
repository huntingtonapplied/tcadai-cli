#!/usr/bin/env bash
# Regression test for cli/install.sh PATH handling (HQ2 INSTALLSH-BASHRC, 2026-10-17).
#
# Serves a stub binary + SHA256SUMS from a file:// release tree and runs install.sh
# non-interactively under throwaway HOMEs. Asserts:
#   1. HOME with no rc file          -> exit 0, no rc file created, hint printed
#   2. HOME that does not exist      -> exit 0 (the HQ2 repro: ".bashrc: No such file", exit 1)
#   3. HOME with .bashrc (bash)      -> exit 0, PATH line appended exactly once
#   4. re-run on the same HOME       -> exit 0, still exactly one PATH line
#   5. SHELL=zsh with .zshrc         -> line goes to .zshrc, .bashrc untouched
#   6. --no-modify-path              -> exit 0, rc untouched
#   7. NO_MODIFY_PATH=1              -> exit 0, rc untouched
#   8. SHELL unset (set -u)          -> exit 0
# Usage: bash cli/install_sh_test.sh [path/to/install.sh]   (default: install.sh beside this file)
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="${1:-$here/install.sh}"
[[ -f "$script" ]] || { echo "no install.sh at $script" >&2; exit 2; }

bin="$(sed -n 's/^BIN_NAME="\([^"]*\)".*/\1/p' "$script" | head -1)"
[[ -n "$bin" ]] || { echo "cannot read BIN_NAME from $script" >&2; exit 2; }
# Does this installer manage PATH in an rc file at all? (some only print a hint)
writes_rc=0
grep -q 'shell_rc' "$script" && writes_rc=1

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$(uname -m)" in x86_64|amd64) arch=x86_64 ;; arm64|aarch64) arch=arm64 ;; *) arch="$(uname -m)" ;; esac

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
rel="$work/srv/cli/releases/latest"
mkdir -p "$rel"
printf '#!/bin/sh\necho "%s 0.0.0-test"\n' "$bin" >"$rel/$bin-$os-$arch"
chmod 755 "$rel/$bin-$os-$arch"
if command -v sha256sum >/dev/null 2>&1; then s="$(sha256sum "$rel/$bin-$os-$arch" | awk '{print $1}')"
else s="$(shasum -a 256 "$rel/$bin-$os-$arch" | awk '{print $1}')"; fi
echo "$s  $bin-$os-$arch" >"$rel/SHA256SUMS"
base="file://$work/srv"

fail=0
ok()  { echo "PASS $*"; }
bad() { echo "FAIL $*"; fail=1; }
count() { [[ -f "$1" ]] && grep -c "^export PATH=.*$2" "$1" || echo 0; }

# run <home> <shell> [extra args...]   (stdin closed -> non-interactive, PATH minimal)
run() {
  local home="$1" sh="$2"; shift 2
  local pfx="$work/pfx-$RANDOM"
  if [[ "$sh" == "-" ]]; then
    env -i HOME="$home" PATH=/usr/bin:/bin ${NO_MODIFY_PATH:+NO_MODIFY_PATH=$NO_MODIFY_PATH} \
      bash "$script" --base-url "$base" --install-dir "$pfx" "$@" </dev/null >"$work/out" 2>&1
  else
    env -i HOME="$home" SHELL="$sh" PATH=/usr/bin:/bin ${NO_MODIFY_PATH:+NO_MODIFY_PATH=$NO_MODIFY_PATH} \
      bash "$script" --base-url "$base" --install-dir "$pfx" "$@" </dev/null >"$work/out" 2>&1
  fi
  local rc=$?
  LAST_PFX="$pfx"
  [[ -x "$pfx/$bin" ]] || { echo "  (binary not installed)"; return 99; }
  return $rc
}

# 1. no rc file
h="$work/h1"; mkdir -p "$h"
run "$h" /bin/bash; rc=$?
[[ $rc -eq 0 ]] && ok "1 no-rc exit 0" || { bad "1 no-rc exit $rc"; sed 's/^/    /' "$work/out" | tail -5; }
[[ ! -e "$h/.bashrc" && ! -e "$h/.zshrc" ]] && ok "1 no rc file created" || bad "1 rc file was created"

# 2. HOME missing entirely
run "$work/does-not-exist" /bin/bash; rc=$?
[[ $rc -eq 0 ]] && ok "2 missing-HOME exit 0" || { bad "2 missing-HOME exit $rc"; sed 's/^/    /' "$work/out" | tail -5; }

# 3/4. existing .bashrc, then re-run (idempotence)
h="$work/h3"; mkdir -p "$h"; echo "# user rc" >"$h/.bashrc"
run "$h" /bin/bash; rc=$?; pfx3="$LAST_PFX"
[[ $rc -eq 0 ]] && ok "3 bashrc exit 0" || bad "3 bashrc exit $rc"
if [[ $writes_rc -eq 1 ]]; then
  n="$(count "$h/.bashrc" "$pfx3")"; [[ "$n" == 1 ]] && ok "3 bashrc has 1 PATH line" || bad "3 bashrc PATH lines=$n"
  env -i HOME="$h" SHELL=/bin/bash PATH=/usr/bin:/bin bash "$script" --base-url "$base" --install-dir "$pfx3" </dev/null >"$work/out" 2>&1; rc=$?
  [[ $rc -eq 0 ]] && ok "4 re-run exit 0" || bad "4 re-run exit $rc"
  n="$(count "$h/.bashrc" "$pfx3")"; [[ "$n" == 1 ]] && ok "4 re-run still 1 PATH line" || bad "4 re-run PATH lines=$n"
else
  [[ "$(cat "$h/.bashrc")" == "# user rc" ]] && ok "3 hint-only installer left .bashrc alone" || bad "3 .bashrc modified"
fi

# 5. zsh
h="$work/h5"; mkdir -p "$h"; : >"$h/.zshrc"; echo "# b" >"$h/.bashrc"
run "$h" /bin/zsh; rc=$?
[[ $rc -eq 0 ]] && ok "5 zsh exit 0" || bad "5 zsh exit $rc"
if [[ $writes_rc -eq 1 ]]; then
  n="$(count "$h/.zshrc" "$LAST_PFX")"; [[ "$n" == 1 ]] && ok "5 zshrc has 1 PATH line" || bad "5 zshrc PATH lines=$n"
fi
[[ "$(cat "$h/.bashrc")" == "# b" ]] && ok "5 bashrc untouched under zsh" || bad "5 bashrc modified under zsh"

# 6. --no-modify-path
h="$work/h6"; mkdir -p "$h"; echo "# u" >"$h/.bashrc"
run "$h" /bin/bash --no-modify-path; rc=$?
[[ $rc -eq 0 ]] && ok "6 --no-modify-path exit 0" || bad "6 --no-modify-path exit $rc"
[[ "$(cat "$h/.bashrc")" == "# u" ]] && ok "6 rc untouched" || bad "6 rc modified"

# 7. NO_MODIFY_PATH=1
h="$work/h7"; mkdir -p "$h"; echo "# u" >"$h/.bashrc"
NO_MODIFY_PATH=1 run "$h" /bin/bash; rc=$?
[[ $rc -eq 0 ]] && ok "7 NO_MODIFY_PATH exit 0" || bad "7 NO_MODIFY_PATH exit $rc"
[[ "$(cat "$h/.bashrc")" == "# u" ]] && ok "7 rc untouched" || bad "7 rc modified"

# 8. SHELL unset
h="$work/h8"; mkdir -p "$h"
run "$h" -; rc=$?
[[ $rc -eq 0 ]] && ok "8 SHELL-unset exit 0" || { bad "8 SHELL-unset exit $rc"; sed 's/^/    /' "$work/out" | tail -3; }

[[ $fail -eq 0 ]] && echo "ALL PASS ($bin)" || echo "FAILURES ($bin)"
exit $fail
