
import logging
import queue
import shutil
import subprocess
import threading
import time

from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


# ==========================================
# CONFIGURATION
# ==========================================

DEV = Path.home() / "dev"

SEPARATOR = "__"

STABLE_CHECKS = 3
CHECK_INTERVAL = 1
MAX_WAIT = 120

IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".idea",
    ".vscode",
    "dist",
    "build",
}

IGNORE_EXTENSIONS = {
    ".tmp",
    ".part",
    ".crdownload",
    ".download",
}

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=LOG_DIR / "auto_git.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

file_queue = queue.Queue()
pending = set()
pending_lock = threading.Lock()


# ==========================================
# LOGGING
# ==========================================

def log(message):
    print(message)
    logging.info(message)


# ==========================================
# GIT COMMANDS
# ==========================================

def git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True
    )


def find_repository(path):
    """Find the nearest Git repository."""

    result = git(path.parent, "rev-parse", "--show-toplevel")

    if result.returncode != 0:
        return None

    root = Path(result.stdout.strip()).resolve()

    # Never use ~/dev itself as a repository.
    if root == DEV.resolve():
        log("[SKIP] ~/dev is an umbrella repository.")
        return None

    try:
        root.relative_to(DEV.resolve())
    except ValueError:
        return None

    return root


# ==========================================
# FILE VALIDATION
# ==========================================

def ignored(path):
    try:
        relative = path.relative_to(DEV.resolve())
    except ValueError:
        return True

    if any(part in IGNORE_DIRS for part in relative.parts):
        return True

    if path.suffix.lower() in IGNORE_EXTENSIONS:
        return True

    return False


def parse_filename(path):
    """
    Format:
    commit-message__actual-filename.extension
    """

    if SEPARATOR not in path.name:
        return None

    message, filename = path.name.split(SEPARATOR, 1)

    message = message.strip().replace("-", " ")
    filename = filename.strip()

    if not message or not filename:
        return None

    # Only allow a filename, never a path.
    if Path(filename).name != filename:
        return None

    # Avoid recursively processing generated files.
    if SEPARATOR in filename:
        return None

    if filename in {".", ".."}:
        return None

    return message, filename


# ==========================================
# FILE STABILITY
# ==========================================

def wait_until_ready(path):
    previous = None
    stable = 0

    for _ in range(MAX_WAIT):
        try:
            stat = path.stat()
            current = (stat.st_size, stat.st_mtime_ns)

        except FileNotFoundError:
            return False

        if current == previous:
            stable += 1
        else:
            stable = 0

        if stable >= STABLE_CHECKS:
            return True

        previous = current
        time.sleep(CHECK_INTERVAL)

    log(f"[TIMEOUT] {path}")
    return False


# ==========================================
# PROCESS FILE
# ==========================================

def process_file(source):

    source = source.resolve()

    if not source.is_file() or ignored(source):
        return

    parsed = parse_filename(source)

    if not parsed:
        return

    message, filename = parsed

    repo = find_repository(source)

    if repo is None:
        log(f"[SKIP] No independent Git repository: {source}")
        return

    # Require a GitHub remote before changing files.
    remote = git(repo, "remote", "get-url", "origin")

    if remote.returncode != 0:
        log(f"[SKIP] No origin remote: {repo}")
        return

    destination = source.parent / filename

    append_mode = destination.exists()

    if append_mode:
        log(f"[APPEND] Existing file found: {destination}")
    else:
        log(f"[CREATE] New file: {destination}")

    try:
        destination.relative_to(repo)
    except ValueError:
        log("[ERROR] Destination is outside the Git repository")
        return

    log("")
    log("=" * 45)
    log(f"[DETECTED] {source}")
    log(f"[REPOSITORY] {repo}")
    log(f"[NEW NAME] {filename}")
    log(f"[COMMIT MESSAGE] {message}")

    # Preserve original download.
    try:
        if append_mode:
            with destination.open("ab") as existing:
                existing.write(b"\n")
                with source.open("rb") as downloaded:
                    shutil.copyfileobj(downloaded, existing)
        else:
            shutil.copy2(source, destination)

    except OSError as error:
        log(f"[ERROR] File operation failed: {error}")
    return

    relative = destination.relative_to(repo)

    # Stage only the generated copy.
    result = git(repo, "add", "--", str(relative))

    if result.returncode != 0:
        log(f"[ERROR] Git add failed: {result.stderr}")
        return

    # Commit only this file.
    result = git(
        repo,
        "commit",
        "--only",
        "-m",
        message,
        "--",
        str(relative)
    )

    if result.returncode != 0:
        log(f"[ERROR] Git commit failed: {result.stderr}")
        return

    log("[SUCCESS] Commit created!")

    # Detect upstream branch.
    upstream = git(
        repo,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{u}"
    )

    if upstream.returncode == 0:
        push = git(repo, "push")
    else:
        push = git(repo, "push", "-u", "origin", "HEAD")

    if push.returncode == 0:
        log("[SUCCESS] Pushed to GitHub!")
    else:
        log(f"[PUSH FAILED] {push.stderr}")

    log(f"[ORIGINAL KEPT] {source}")
    log("=" * 45)


# ==========================================
# QUEUE WORKER
# ==========================================

def worker():

    while True:
        path = file_queue.get()

        if path is None:
            file_queue.task_done()
            break

        try:
            if wait_until_ready(path):
                process_file(path)

        except Exception as error:
            log(f"[ERROR] {error}")

        finally:
            with pending_lock:
                pending.discard(path)

            file_queue.task_done()


# ==========================================
# WATCHDOG HANDLER
# ==========================================

class AutoGitHandler(FileSystemEventHandler):

    def enqueue(self, source):

        path = Path(source).resolve()

        if ignored(path):
            return

        if not path.is_relative_to(DEV.resolve()):
            return

        with pending_lock:
            if path in pending:
                return

            pending.add(path)

        file_queue.put(path)

    def on_created(self, event):
        if not event.is_directory:
            self.enqueue(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.enqueue(event.dest_path)


# ==========================================
# MAIN
# ==========================================

def main():

    if not DEV.is_dir():
        print(f"[ERROR] Development folder not found: {DEV}")
        return

    print("=" * 50)
    print("              GLOBAL AUTO GIT")
    print("=" * 50)
    print(f"Monitoring : {DEV}")
    print("Scope      : Individual Git repositories")
    print("Recursive  : Enabled")
    print("Originals  : Preserved")
    print("Actions    : Copy -> Add -> Commit -> Push")
    print("=" * 50)

    thread = threading.Thread(
        target=worker,
        daemon=True
    )
    thread.start()

    observer = Observer()

    observer.schedule(
        AutoGitHandler(),
        str(DEV),
        recursive=True
    )

    observer.start()

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping Global Auto Git...")

        observer.stop()
        observer.join()

        file_queue.join()
        file_queue.put(None)
        file_queue.join()

        thread.join()

        print("Watcher stopped.")


if __name__ == "__main__":
    main()
