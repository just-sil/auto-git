
import argparse
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

# Default: Never push automatically.
AUTO_PUSH = False

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
    print(message, flush=True)
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
    """Find the nearest independent Git repository."""

    result = git(path.parent, "rev-parse", "--show-toplevel")

    if result.returncode != 0:
        return None

    root = Path(result.stdout.strip()).resolve()

    # Never use ~/dev as one giant repository.
    if root == DEV.resolve():
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

    # Prevent directory traversal.
    if Path(filename).name != filename:
        return None

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

    # Find the nearest project repository.
    repo = find_repository(source)

    if repo is None:
        log(f"[SKIP] No independent Git repository: {source}")
        return

    destination = source.parent / filename

    # Make sure destination is inside the repository.
    try:
        relative = destination.relative_to(repo)
    except ValueError:
        log("[ERROR] Destination is outside the repository")
        return

    # Reject directory destinations.
    if destination.exists() and not destination.is_file():
        log(f"[ERROR] Destination is not a regular file: {destination}")
        return

    log("")
    log("=" * 50)
    log(f"[DETECTED] {source}")
    log(f"[REPOSITORY] {repo}")
    log(f"[TARGET] {filename}")
    log(f"[COMMIT MESSAGE] {message}")

    # ======================================
    # COPY / OVERWRITE
    # ======================================

    try:
        if destination.exists():
            log(f"[OVERWRITE] Existing file: {destination}")
        else:
            log(f"[CREATE] New file: {destination}")

        # Original download remains untouched.
        # Existing destination is completely replaced.
        shutil.copy2(source, destination)

    except OSError as error:
        log(f"[ERROR] Copy failed: {error}")
        return

    log("[SUCCESS] File copied")

    # ======================================
    # GIT ADD
    # ======================================

    result = git(repo, "add", "--", str(relative))

    if result.returncode != 0:
        log(f"[ERROR] Git add failed: {result.stderr}")
        return

    log("[SUCCESS] Git add")

    # ======================================
    # GIT COMMIT
    # ======================================

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
        log(f"[COMMIT FAILED] {result.stdout}{result.stderr}")
        return

    log("[SUCCESS] Local commit created")

    # ======================================
    # PUSH CONTROL
    # ======================================

    if not AUTO_PUSH:

        log("[MANUAL PUSH] GitHub push disabled")
        log(f"[PROJECT] {repo}")
        log(f"[COMMAND] git -C \"{repo}\" push")
        log(f"[ORIGINAL KEPT] {source}")
        log("=" * 50)

        return

    # ======================================
    # AUTOMATIC PUSH
    # ======================================

    remote = git(repo, "remote", "get-url", "origin")

    if remote.returncode != 0:
        log("[PUSH FAILED] No origin remote configured")
        return

    upstream = git(
        repo,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{u}"
    )

    if upstream.returncode == 0:
        push_args = ["git", "push"]
    else:
        push_args = ["git", "push", "-u", "origin", "HEAD"]

    log("[PUSHING] Uploading to GitHub...")

    try:
        push = subprocess.run(
            push_args,
            cwd=repo,
            text=True
        )

        if push.returncode == 0:
            log("[SUCCESS] Pushed to GitHub!")
        else:
            log(f"[PUSH FAILED] Exit code: {push.returncode}")

    except Exception as error:
        log(f"[PUSH ERROR] {error}")

    log(f"[ORIGINAL KEPT] {source}")
    log("=" * 50)


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

    global AUTO_PUSH

    parser = argparse.ArgumentParser(
        description="Global automatic Git file manager"
    )

    parser.add_argument(
        "--auto-push",
        action="store_true",
        help="Automatically push commits to GitHub"
    )

    args = parser.parse_args()

    AUTO_PUSH = args.auto_push

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
    print("Overwrite  : Enabled")
    print("Git Add    : Automatic")
    print("Git Commit : Automatic")
    print(f"Git Push   : {'AUTOMATIC' if AUTO_PUSH else 'MANUAL'}")

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
