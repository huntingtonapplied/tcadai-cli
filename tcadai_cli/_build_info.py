"""Build identity. The committed value is empty; cli/scripts/build_binary.sh stamps the source commit here
before PyInstaller runs, so a shipped binary can say which commit it was built from
(R1103-BINARY-CLI-NO-COMMIT-STALE-MANIFEST)."""
import os

COMMIT = ""  # stamped by build_binary.sh (40-hex sha)


def get_commit() -> str:
    """The stamped commit, else $BOLTZMANN_BUILD_ID, else "unknown"."""
    return COMMIT or os.environ.get("BOLTZMANN_BUILD_ID", "").strip() or "unknown"


def version_message() -> str:
    from tcadai_cli import __version__
    commit = get_commit()
    short = commit[:12] if commit != "unknown" else commit
    return f"%(prog)s, version {__version__} (commit {short})"
