# Copyright 2026 Vainu Finland Oy — MIT License
"""Automatically track large files in Git LFS when they exceed a threshold."""

import argparse
import contextlib
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# File-type classification defaults
# ---------------------------------------------------------------------------

_BINARY_SUFFIXES = frozenset({".pdf", ".7z", ".bz2", ".bzip2", ".gz", ".zip"})
_TEXT_SUFFIXES   = frozenset({".json", ".toml", ".xml", ".yaml", ".yml", ".csv", ".tsv"})


def _gitattributes_type_rules() -> list[tuple[str, bool]]:
    """Parse .gitattributes for text/binary declarations.

    Returns ``[(pattern, is_binary), ...]`` in file order; later entries take
    precedence (last-match-wins, mirroring git).  LFS-tracked lines are
    excluded — they are handled by :func:`lfs_tracked_patterns`.
    """
    ga = Path(".gitattributes")
    if not ga.exists():
        return []
    rules: list[tuple[str, bool]] = []
    for line in ga.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern, attrs = parts[0], set(parts[1:])
        if "filter=lfs" in attrs:
            continue  # LFS entries handled elsewhere
        if "binary" in attrs or "-text" in attrs:
            rules.append((pattern, True))
        elif "text" in attrs or "eol=crlf" in attrs or "eol=lf" in attrs:
            rules.append((pattern, False))
    return rules


def _file_is_binary(path: Path, ga_rules: list[tuple[str, bool]]) -> bool | None:
    """Classify *path* as binary (``True``), text (``False``), or unknown (``None``).

    Priority: .gitattributes rules (last match wins) → hardcoded extension defaults.
    """
    result: bool | None = None
    for pattern, is_binary in ga_rules:
        if path.match(pattern):
            result = is_binary
    if result is not None:
        return result
    suffix = path.suffix.lower()
    if suffix in _BINARY_SUFFIXES:
        return True
    if suffix in _TEXT_SUFFIXES:
        return False
    return None


def should_track(
    path: Path,
    max_lines: int,
    max_bytes: int,
    ga_rules: list[tuple[str, bool]] | None = None,
) -> bool:
    """Return ``True`` if *path* exceeds its relevant threshold.

    All files are checkd against max_bytes, text (non-binary) files then against max_lines.
    Returns ``False`` if the file cannot be read.
    """
    is_binary = _file_is_binary(path, ga_rules or [])
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size > max_bytes:
        return True
    if is_binary is False:
        with contextlib.suppress(OSError):
            return sum(1 for _ in path.open(encoding="utf-8", errors="replace")) > max_lines
    return False


def lfs_tracked_patterns() -> set[str]:
    """Return the set of glob patterns currently tracked by Git LFS."""
    ga = Path(".gitattributes")
    if not ga.exists():
        return set()
    patterns: set[str] = set()
    for line in ga.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and any("filter=lfs" in p for p in parts[1:]):
            patterns.add(parts[0])
    return patterns


def already_lfs_tracked(path: Path, patterns: set[str]) -> bool:
    """Return ``True`` if *path* is already covered by an LFS pattern."""
    return any(path.match(pat) for pat in patterns)


def track_pattern_for(path: Path) -> str:
    """Return the LFS tracking glob for *path* (extension-based when possible)."""
    return f"*{path.suffix}" if path.suffix else path.name


def lfs_available() -> bool:
    """Return ``True`` if git-lfs is installed and reachable."""
    try:
        return subprocess.run(["git", "lfs", "version"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auto-track large files in Git LFS.")
    parser.add_argument(
        "--max-lines",
        type=int,
        default=3000,
        metavar="N",
        help="Line threshold for text files; files above this are moved to LFS (default: 3000).",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=10 * 1024 * 1024,
        metavar="N",
        help="Size threshold for binary files in bytes (default: 10 MiB).",
    )
    parser.add_argument(
        "--glob",
        dest="globs",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Glob pattern a file must match to be eligible (repeatable). "
            "When omitted, all files passed by pre-commit are checked."
        ),
    )
    parser.add_argument("filenames", nargs="*")
    args = parser.parse_args(argv)

    if not args.filenames:
        return 0

    if not lfs_available():
        print(
            "git-lfs-autotrack: git-lfs is not installed. "
            "Install it from https://git-lfs.github.com/",
            file=sys.stderr,
        )
        return 1

    current_patterns = lfs_tracked_patterns()
    ga_rules = _gitattributes_type_rules()
    candidates: list[Path] = []

    for path in (Path(f) for f in args.filenames):
        if already_lfs_tracked(path, current_patterns):
            continue
        if args.globs and not any(path.match(g) for g in args.globs):
            continue
        if should_track(path, args.max_lines, args.max_bytes, ga_rules):
            candidates.append(path)

    if not candidates:
        return 0

    print(f"git-lfs-autotrack: {len(candidates)} file(s) exceed threshold — moving to Git LFS:")

    converted: list[Path] = []
    failed: list[Path] = []

    for path in candidates:
        pattern = track_pattern_for(path)
        try:
            subprocess.run(["git", "lfs", "track", pattern], check=True, capture_output=True)
            # Unstage the regular blob and re-add as an LFS pointer.
            subprocess.run(["git", "rm", "--cached", "--quiet", str(path)], check=True, capture_output=True)
            subprocess.run(["git", "add", str(path)], check=True, capture_output=True)
            converted.append(path)
            print(f"  {path}  →  tracked as {pattern!r}")
        except subprocess.CalledProcessError as exc:
            failed.append(path)
            print(f"  ERROR {path}: {exc}", file=sys.stderr)

    if converted:
        subprocess.run(["git", "add", ".gitattributes"], check=True, capture_output=True)
        print(
            f"\ngit-lfs-autotrack: {len(converted)} file(s) converted."
            " .gitattributes updated and files re-staged as LFS pointers."
            "\nCommit aborted — please re-run your commit to continue."
        )

    return 1 if (converted or failed) else 0


if __name__ == "__main__":
    sys.exit(main())
