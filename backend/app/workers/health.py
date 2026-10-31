import socket
from app.workers.celery_app import celery_app
from app.workers.supervisor import WORKERS


def check():
    nodes = {name + "@" + socket.gethostname(): set(queues.split(',')) for name, queues, _ in WORKERS}
    actual = celery_app.control.inspect(destination=list(nodes), timeout=5).active_queues() or {}
    for node, expected in nodes.items():
        if {queue['name'] for queue in actual.get(node, [])} != expected:
            raise SystemExit('Worker queues unavailable: ' + node)
    print('Sync, AI and send workers have reserved queue capacity.')


if __name__ == '__main__':
    check()
