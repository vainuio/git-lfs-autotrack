# git-lfs-autotrack

A [pre-commit](https://pre-commit.com) hook that automatically moves large files into [Git LFS](https://git-lfs.github.com/) when they exceed a configurable threshold.

## How it works

When a staged file exceeds its threshold, the hook:

1. Runs `git lfs track <pattern>` (e.g. `*.json`) to add an entry to `.gitattributes`
2. Unstages the regular blob and re-adds it as an LFS pointer
3. Stages the updated `.gitattributes`
4. Exits non-zero to abort the commit

Re-run the commit, and it goes through cleanly as an LFS pointer commit.

## Requirements

- Python 3.12+
- [git-lfs](https://git-lfs.github.com/) installed and on `PATH`

## Usage

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/vainuio/git-lfs-autotrack
    rev: v0.1.0
    hooks:
      - id: git-lfs-autotrack
        args:
          - --max-lines=3000
          - --glob=**/data/*
          - --glob=**/_data/*
```

### Default exclusions

The hook manifest excludes source-code extensions across all major languages (Python, JS/TS, Go, Rust, Java, C/C++, Ruby, PHP, shell, Haskell, Clojure, Elixir, Scala, Lua, HCL, and many more) so that source files are never accidentally moved to LFS.

To override the exclusion list entirely, set `exclude` in your hook config (this replaces the manifest default):

```yaml
hooks:
  - id: git-lfs-autotrack
    exclude: '^$'   # exclude nothing — all files are eligible
```

Or supply your own pattern:

```yaml
hooks:
  - id: git-lfs-autotrack
    exclude: '\.(py|js|ts)$'
```

## Arguments

| Argument | Default | Description |
|---|---|---|
| `--max-lines=N` | `10000` | Line threshold for known-text files |
| `--max-bytes=N` | `10485760` (10 MiB) | Byte threshold; applied to all files |
| `--glob=PATTERN` | *(all files)* | Restrict to files matching this glob (repeatable) |

## Thresholds

Every file is checked against `--max-bytes` first. If the file exceeds that limit it is moved to LFS regardless of type.

For files within the byte limit, only **text** files are checked against `--max-lines`. Binary and unrecognised files are not tracked unless they exceed `--max-bytes`.

## File-type classification

The hook classifies files using two sources, checked in this order:

1. **`.gitattributes`** — `text`, `eol=crlf`, or `eol=lf` → text; `binary` or `-text` → binary. Lines with `filter=lfs` are skipped (already tracked).
2. **Built-in extension defaults:**

   | Binary | Text |
   |---|---|
   | `.pdf` `.7z` `.bz2` `.bzip2` `.gz` `.zip` | `.json` `.toml` `.xml` `.yaml` `.yml` `.csv` |

Files with unrecognised extensions are treated as binary (byte threshold only).

## Standalone use

```sh
# via uvx (no install required)
uvx git-lfs-autotrack --max-lines=3000 path/to/file.json

# or install into a virtualenv
pip install git-lfs-autotrack
git-lfs-autotrack --max-lines=3000 path/to/file.json
```
