"""Three Celery processes reserve queue capacity inside the existing worker service."""
import signal
import socket
import subprocess
import sys
import time

WORKERS = (("mailbox", "gmail-sync,gmail-maintenance", 2), ("ai", "gmail-ai", 2), ("send", "gmail-send", 1))


def commands():
    return [[sys.executable, "-m", "celery", "-A", "app.workers.celery_app:celery_app", "worker",
             "--hostname=" + name + "@" + socket.gethostname(), "-Q", queues,
             "--concurrency=" + str(concurrency), "--loglevel=INFO"] for name, queues, concurrency in WORKERS]


def main():
    children = []
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True
        for child in children:
            if child.poll() is None:
                child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for command in commands():
            children.append(subprocess.Popen(command))
        while not stopping:
            if any(child.poll() is not None for child in children):
                stop()
                return 1  # Docker restarts the entire group if one worker exits.
            time.sleep(0.5)
        return 0
    finally:
        stop()
        for child in children:
            child.wait()  # Compose's stop grace period bounds warm shutdown.


if __name__ == "__main__":
    sys.exit(main())
