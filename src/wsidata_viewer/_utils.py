"""Utility helpers."""
from __future__ import annotations

import socket
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uvicorn
    from fastapi import FastAPI


def find_free_port() -> int:
    """Return an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def start_server_thread(
    app: FastAPI,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> uvicorn.Server:
    """Start a uvicorn server in a daemon thread and return the Server object."""
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait until the server is ready (up to 5 s)
    deadline = time.time() + 5
    while not server.started and time.time() < deadline:
        time.sleep(0.05)

    return server
