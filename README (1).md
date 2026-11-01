# Auto Git

A Python-based file automation utility that monitors `~/dev` recursively and manages independent Git repositories.

It detects specially named files, creates or replaces their intended destination files, stages and commits the result, and optionally pushes to GitHub.

## Filename convention

Use:

```text
commit-message__actual-filename.extension
```

Example:

```text
Move utility poles off road__index.html
```

- Text before `__` becomes the Git commit message.
- Text after `__` becomes the final filename.
- Hyphens in the commit message are converted to spaces.
- The separator is exactly two underscores.

## Workflow

When a matching new file is created or moved into a monitored project:

1. Wait for the file to stop changing.
2. Parse the commit message and target filename.
3. Find the nearest independent Git repository containing the file.
4. Copy the downloaded file to the target path beside the original.
5. If the target already exists, **overwrite it completely**.
6. Keep the original downloaded file unchanged.
7. Run `git add` for the target file only.
8. Create a local commit using the extracted commit message.
9. Push only when automatic push mode is explicitly enabled.

## Push modes

### Manual push — default

Start the watcher with:

```bash
python3 auto_git.py
```

Files are copied, staged and committed locally. Auto Git does not push to GitHub.

Push manually from the relevant project repository:

```bash
cd ~/dev/your-project
git push
```

### Automatic push — opt-in

Start the watcher with:

```bash
python3 auto_git.py --auto-push
```

After each successful local commit, Auto Git attempts to push the repository's current branch to its configured `origin` remote.

## Example

Input file:

```text
~/dev/kerala-drive/Move utility poles off road__index.html
```

Result:

```text
~/dev/kerala-drive/
├── .git/
├── index.html
└── Move utility poles off road__index.html
```

Git commit:

```bash
git add index.html
git commit -m "Move utility poles off road"
```

The downloaded original remains in place. The existing `index.html`, if any, is replaced by the downloaded file's contents.

## Directory monitoring

Auto Git watches:

```text
~/dev/
```

It monitors subdirectories recursively. Each file is associated with the nearest independent Git repository.

The `~/dev` directory itself is deliberately not accepted as a project repository. Projects without their own Git repository are skipped. Auto Git does not initialize repositories or create remotes.

## Ignored directories

The watcher skips paths containing:

- `.git`
- `.venv`
- `venv`
- `__pycache__`
- `node_modules`
- `.idea`
- `.vscode`
- `dist`
- `build`

## Ignored file extensions

- `.tmp`
- `.part`
- `.crdownload`
- `.download`

Files without the `__` separator are ignored.

## Installation

From the Auto Git project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install watchdog
```

## Run

Manual push mode:

```bash
python3 auto_git.py
```

Automatic push mode:

```bash
python3 auto_git.py --auto-push
```

Stop the watcher with `Ctrl+C`.

## Logs

Runtime activity is recorded in:

```text
logs/auto_git.log
```

## Requirements

- Python 3
- Git
- Python package `watchdog`
- An independent Git repository for each project
- An `origin` remote configured for projects that need pushing
- GitHub authentication configured for manual or automatic pushes

## Important behaviour and limitations

- Original downloaded files are preserved.
- Existing destination files are overwritten completely, not appended.
- The destination is created beside the downloaded original.
- Only the destination file is staged and included in the automatic commit.
- Unrelated staged changes are not intentionally included in that commit.
- Push is disabled by default.
- Push failures do not undo the local commit.
- The watcher handles newly created and moved files; it does not monitor edits to existing files.
- Existing uncommitted content in an overwritten destination can be lost. Commit or back up important work first.
- The current implementation uses a single worker, so files are processed sequentially.
- A file copied into a destination with the same name as its source is not a useful input and should be avoided.

## Project goal

Make file-based Git workflows convenient while keeping the original downloads and leaving control of GitHub publishing with the user by default.
