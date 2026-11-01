# Auto Git

An automated Git workflow that watches your development directory and handles file naming, staging, committing, and pushing to GitHub.

## How it works

Auto Git monitors `~/dev` and all its subdirectories recursively.

When a newly downloaded file follows the naming convention, it automatically processes it.

### Filename convention

```text
commit-message__actual-filename.extension
```

Example:

```text
added new feature__feature.py
```

Auto Git interprets this as:

- **Commit message:** `added new feature`
- **Final filename:** `feature.py`

## Workflow

1. Detect a newly created or downloaded file.
2. Wait until the download is complete.
3. Extract the commit message and actual filename.
4. Identify the nearest independent Git repository.
5. Create a renamed copy while preserving the original download.
6. Stage the resulting file.
7. Commit using the extracted message.
8. Push to the repository's GitHub remote.

## Existing file handling

If the destination file already exists, Auto Git appends the downloaded file's contents to the existing file.

Example:

```text
added section__index.html
```

If `index.html` already exists, the new content is appended to it. The original downloaded file remains untouched.

**Note:** Appending is currently a raw byte-level operation, not an HTML-aware merge. For HTML files, this can produce duplicate document structure such as multiple `<html>`, `<head>`, or `<body>` elements.

## Directory structure

```text
~/dev/
├── auto-git/
│   ├── auto-git.py
│   └── logs/
├── kerala-drive/
│   ├── .git/
│   └── ...
└── other-project/
    ├── .git/
    └── ...
```

Each project maintains its own Git history and remote.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install watchdog
```

## Run

```bash
python3 auto-git.py
```

## Requirements

- Python 3
- Git
- Python Watchdog
- Independent Git repositories
- Configured GitHub `origin` remote
- Working GitHub authentication (SSH recommended)

## Logs

Activity is recorded in:

```text
auto-git/logs/auto_git.log
```

## Safety and limitations

- Original downloads are preserved.
- Existing destination files are appended to rather than overwritten.
- Files without the `__` separator are ignored.
- Dependency and temporary directories are excluded.
- Projects without independent Git repositories are skipped.
- Push failures leave the local commit intact.
- The current watcher handles new files and completed downloads, not edits to existing files.
- A raw append is not suitable for every file type; binary files and structured formats may need a merge strategy specific to that format.

## Project goal

Make file-based Git workflows automatic: download, name, commit, and push without manually repeating Git commands.
