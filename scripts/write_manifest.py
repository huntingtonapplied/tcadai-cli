#!/usr/bin/env python3
"""Write cli/releases/<version>/manifest.json from the binaries that will actually be served, so the
manifest version, commit and sha256 cannot drift from the files (R1103-BINARY-CLI-NO-COMMIT-STALE-MANIFEST:
latest/manifest.json said 1.0.2 / sha 89cd3bce while the served darwin binary was 69c3cb26).

  write_manifest.py --version 1.0.4 --commit <40-hex> --binary darwin-arm64=dist/tcadai-darwin-arm64 \
      --binary linux-x86_64=dist/tcadai-linux-x86_64 --out manifest.json
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(version: str, commit: str, binaries: dict) -> dict:
    if not SEMVER.match(version or ""):
        raise ValueError(f"invalid version: {version!r}")
    if not SHA.match(commit or ""):
        raise ValueError(f"invalid commit: {commit!r} (want a full 40-hex sha)")
    if not binaries:
        raise ValueError("no binaries given")
    files = {}
    for platform, path in sorted(binaries.items()):
        p = Path(path)
        if not p.is_file():
            raise ValueError(f"binary for {platform} not found: {path}")
        files[platform] = {"file": p.name, "sha256": sha256_file(p), "size": p.stat().st_size}
    return {"version": version, "commit": commit, "binaries": files}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--binary", action="append", required=True, metavar="PLATFORM=PATH")
    ap.add_argument("--out", default="-")
    a = ap.parse_args(argv)
    try:
        bins = dict(item.split("=", 1) for item in a.binary)
        manifest = build_manifest(a.version, a.commit, bins)
    except ValueError as e:
        print(f"!! write_manifest: {e}", file=sys.stderr)
        return 2
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if a.out == "-":
        sys.stdout.write(text)
    else:
        Path(a.out).write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
