from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from git_lfs_autotrack.__main__ import (
    _gitattributes_type_rules,
    already_lfs_tracked,
    lfs_tracked_patterns,
    main,
    should_track,
    track_pattern_for,
)


# ---------------------------------------------------------------------------
# should_track
# ---------------------------------------------------------------------------

def test_should_track_small_text(tmp_path):
    f = tmp_path / "small.json"
    f.write_text("\n".join(str(i) for i in range(5)), encoding="utf-8")
    assert should_track(f, max_lines=100, max_bytes=1000) is False


def test_should_track_large_text(tmp_path):
    f = tmp_path / "big.json"
    f.write_text("\n".join(str(i) for i in range(200)), encoding="utf-8")
    assert should_track(f, max_lines=100, max_bytes=1000) is True


def test_should_track_binary_below_size(tmp_path):
    f = tmp_path / "small.bin"
    f.write_bytes(b"\xff\x80" * 5)
    assert should_track(f, max_lines=100, max_bytes=1000) is False


def test_should_track_binary_above_size(tmp_path):
    f = tmp_path / "big.bin"
    f.write_bytes(b"\xff\x80" * 600)  # 1200 bytes
    assert should_track(f, max_lines=100, max_bytes=1000) is True


def test_should_track_missing_file():
    assert should_track(Path("/nonexistent.txt"), max_lines=100, max_bytes=1000) is False


# ---------------------------------------------------------------------------
# _gitattributes_type_rules
# ---------------------------------------------------------------------------

def test_gitattributes_type_rules_parses_text_and_binary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitattributes").write_text(
        "*.pdf    binary\n"
        "*.gz     -text\n"
        "*.csv    text eol=crlf\n"
        "*.json   filter=lfs diff=lfs merge=lfs -text\n",  # LFS — excluded
        encoding="utf-8",
    )
    rules = _gitattributes_type_rules()
    assert ("*.pdf", True) in rules
    assert ("*.gz", True) in rules
    assert ("*.csv", False) in rules
    assert not any(pat == "*.json" for pat, _ in rules)


def test_gitattributes_type_rules_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _gitattributes_type_rules() == []


# ---------------------------------------------------------------------------
# should_track — extension defaults and .gitattributes override
# ---------------------------------------------------------------------------

def test_should_track_large_text_single_line(tmp_path):
    """Text file over max_bytes is tracked even with only one line."""
    f = tmp_path / "big.json"
    f.write_bytes(b"x" * 1100)  # 1 line, but 1100 bytes > max_bytes=1000
    assert should_track(f, max_lines=100, max_bytes=1000) is True


def test_should_track_known_binary_extension(tmp_path):
    """Known binary extension (.pdf) uses byte threshold even if content is valid UTF-8."""
    f = tmp_path / "doc.pdf"
    f.write_text("\n".join(str(i) for i in range(200)), encoding="utf-8")
    # 200 lines but PDF → byte threshold; file is small → not tracked
    assert should_track(f, max_lines=100, max_bytes=100_000) is False


def test_should_track_gitattributes_overrides_extension(tmp_path):
    """A ga_rule marking *.json as binary overrides the built-in text default."""
    f = tmp_path / "data.json"
    f.write_text("\n".join(str(i) for i in range(200)), encoding="utf-8")
    # Built-in default: .json is text → 200 lines > 100 → True
    assert should_track(f, max_lines=100, max_bytes=100_000) is True
    # Explicit binary override with large max_bytes → False
    assert should_track(f, max_lines=100, max_bytes=100_000, ga_rules=[("*.json", True)]) is False


# ---------------------------------------------------------------------------
# lfs_tracked_patterns
# ---------------------------------------------------------------------------

def test_lfs_tracked_patterns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitattributes").write_text(
        "*.json filter=lfs diff=lfs merge=lfs -text\n"
        "*.csv  filter=lfs diff=lfs merge=lfs -text\n"
        "*.py   diff=python\n",
        encoding="utf-8",
    )
    patterns = lfs_tracked_patterns()
    assert "*.json" in patterns
    assert "*.csv" in patterns
    assert "*.py" not in patterns


def test_lfs_tracked_patterns_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert lfs_tracked_patterns() == set()


# ---------------------------------------------------------------------------
# already_lfs_tracked  (documents Path.match expectations)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path,pattern,expected", [
    ("data/file.json",          "*.json",       True),
    ("data/file.json",          "**/data/*",    False),  # no prefix segment for **
    ("a/b/data/file.json",      "**/data/*",    True),
    ("a/_data/file.toml",       "**/_data/*",   True),
    ("src/config.json",         "**/data/*",    False),
    ("file.csv",                "*.json",       False),
])
def test_already_lfs_tracked(path, pattern, expected):
    assert already_lfs_tracked(Path(path), {pattern}) is expected


def test_already_lfs_tracked_empty_patterns():
    assert already_lfs_tracked(Path("data/big.json"), set()) is False


# ---------------------------------------------------------------------------
# track_pattern_for
# ---------------------------------------------------------------------------

def test_track_pattern_with_extension():
    assert track_pattern_for(Path("data/big.json")) == "data/big.json"


def test_track_pattern_no_extension():
    assert track_pattern_for(Path("Makefile")) == "Makefile"


def test_track_pattern_nested():
    assert track_pattern_for(Path("a/b/c.toml")) == "a/b/c.toml"


# ---------------------------------------------------------------------------
# main — integration
# ---------------------------------------------------------------------------

def _large_file(path: Path, lines: int) -> None:
    path.write_text("\n".join(str(i) for i in range(lines)), encoding="utf-8")


def test_main_no_files():
    assert main([]) == 0


def test_main_small_file_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitattributes").write_bytes(b"")
    f = tmp_path / "small.json"
    f.write_text('{"x": 1}\n', encoding="utf-8")
    with patch("git_lfs_autotrack.__main__.lfs_available", return_value=True):
        assert main(["--max-lines=100", str(f)]) == 0


def test_main_lfs_unavailable_returns_1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "big.json"
    _large_file(f, 200)
    with patch("git_lfs_autotrack.__main__.lfs_available", return_value=False):
        assert main(["--max-lines=100", str(f)]) == 1


def test_main_large_file_is_converted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitattributes").write_bytes(b"")
    f = tmp_path / "big.json"
    _large_file(f, 200)

    run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    with (
        patch("git_lfs_autotrack.__main__.lfs_available", return_value=True),
        patch("git_lfs_autotrack.__main__.subprocess.run", run),
    ):
        result = main(["--max-lines=100", str(f)])

    assert result == 1
    lfs_track_calls = [c for c in run.call_args_list if c.args[0][:3] == ["git", "lfs", "track"]]
    assert len(lfs_track_calls) == 1
    assert lfs_track_calls[0].args[0][3] == Path(str(f)).as_posix()


def test_main_glob_filter_excludes_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitattributes").write_bytes(b"")
    f = tmp_path / "big.json"
    _large_file(f, 200)

    with patch("git_lfs_autotrack.__main__.lfs_available", return_value=True):
        assert main(["--max-lines=100", "--glob=**/data/*", str(f)]) == 0


def test_main_glob_filter_includes_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitattributes").write_bytes(b"")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    f = data_dir / "big.json"
    _large_file(f, 200)

    run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    with (
        patch("git_lfs_autotrack.__main__.lfs_available", return_value=True),
        patch("git_lfs_autotrack.__main__.subprocess.run", run),
    ):
        assert main(["--max-lines=100", "--glob=**/data/*", str(f)]) == 1


def test_main_already_tracked_skipped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitattributes").write_text(
        "*.json filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8"
    )
    f = tmp_path / "big.json"
    _large_file(f, 200)

    with patch("git_lfs_autotrack.__main__.lfs_available", return_value=True):
        assert main(["--max-lines=100", str(f)]) == 0


def test_main_binary_below_size_skipped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitattributes").write_bytes(b"")
    f = tmp_path / "img.png"
    f.write_bytes(b"\xff\x80" * 10)  # 20 bytes, well below default max-bytes

    with patch("git_lfs_autotrack.__main__.lfs_available", return_value=True):
        assert main(["--max-lines=1", "--max-bytes=1000", str(f)]) == 0


def test_main_binary_above_size_converted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitattributes").write_bytes(b"")
    f = tmp_path / "big.bin"
    f.write_bytes(b"\xff\x80" * 600)  # 1200 bytes

    run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    with (
        patch("git_lfs_autotrack.__main__.lfs_available", return_value=True),
        patch("git_lfs_autotrack.__main__.subprocess.run", run),
    ):
        assert main(["--max-lines=1", "--max-bytes=1000", str(f)]) == 1
