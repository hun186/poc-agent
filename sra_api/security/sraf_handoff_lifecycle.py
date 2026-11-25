"""Supervise one optional private listener inside the existing API event loop.

Only the single-process api.run_api launcher supplies the actual public port.
Prebind the configured private socket; never compete with the future public
bind, use proxy headers, install process signal handlers, or create a Worker.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import logging
from pathlib import Path
import socket

import uvicorn

from api.security.sraf_handoff_assertion import HandoffDenied
from api.security.sraf_handoff_config import load_handoff_receiver_config
from api.security.sraf_handoff_ingress import build_private_ingress

_LOG = logging.getLogger("uvicorn.error")


class _PrivateServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        yield

    def install_signal_handlers(self):
        # Compatibility with older supported Uvicorn releases.
        return None


class PrivateListenerRuntime:
    def __init__(self, app, config):
        self.app = app
        self.accepting = False
        cfg = build_private_ingress(app, config.listener, config.trust,
                                    config.mapping, config.replay,
                                    admission_open=lambda: self.accepting)
        cfg.load()
        self.server = _PrivateServer(cfg)
        self.task = None
        self.stopping = False
        family = socket.AF_INET6 if ":" in config.listener.bind_host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            # Never SO_REUSEPORT. On Windows, exclusive bind avoids stealing
            # another listener; on POSIX allow only TIME_WAIT rebind.
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            sock.bind((config.listener.bind_host, config.listener.port))
            sock.listen(128)
            sock.setblocking(False)
        except BaseException:
            sock.close()
            raise
        self.socket = sock

    async def _run(self):
        try:
            await self.server.serve(sockets=[self.socket])
        except (Exception, SystemExit):
            # Uvicorn can raise SystemExit on bind/start errors; isolate the
            # optional service rather than terminate the entire API.
            self.app.state.handoff_listener_status = "FAILED_RUNTIME"
            _LOG.warning("SRAF handoff listener unavailable")
        finally:
            self.accepting = False
            for listener in getattr(self.server, "servers", ()):
                listener.close()
                await listener.wait_closed()
            self.socket.close()
            if self.stopping:
                self.app.state.handoff_listener_status = "STOPPED"
            else:
                self.app.state.handoff_listener_status = "FAILED_RUNTIME"

    async def start(self):
        self.task = asyncio.create_task(self._run())
        deadline = asyncio.get_running_loop().time() + 5
        while not self.server.started and not self.task.done():
            if asyncio.get_running_loop().time() >= deadline:
                await self.stop()
                raise HandoffDenied("handoff_listener_start_timeout")
            await asyncio.sleep(0.01)
        if self.task.done() or not self.server.started:
            await self.stop()
            raise HandoffDenied("handoff_listener_start_failed")
        self.accepting = True
        self.app.state.handoff_listener_status = "RUNNING"

    async def stop(self):
        # Stop admissions before worker shutdown. Drain already admitted
        # synchronous Agent calls rather than canceling their awaiters and
        # releasing shared state while the underlying threads still run.
        self.accepting = False
        self.stopping = True
        self.server.should_exit = True
        if self.task is not None:
            await asyncio.shield(self.task)
        else:
            self.socket.close()
            self.app.state.handoff_listener_status = "STOPPED"


async def start_optional_handoff(app, env, *, project_root: Path):
    """Expected local configuration/listener failures leave ordinary API alive."""
    app.state.handoff_listener_status = "DISABLED"
    app.state.handoff_listener_runtime = None
    if env.get("SRAF_HANDOFF_ENABLED", "0") == "0":
        return None
    public_port = getattr(app.state, "handoff_public_listener_port", None)
    if type(public_port) is not int or not 1 <= public_port <= 65535:
        app.state.handoff_listener_status = "DISABLED_UNSUPPORTED_LAUNCHER"
        _LOG.warning("SRAF handoff disabled: requires the single-process api.run_api launcher")
        return None
    runtime = None
    try:
        cfg = load_handoff_receiver_config(env, project_root=project_root)
        if cfg is None or cfg.listener.port == public_port:
            raise HandoffDenied("handoff_listener_conflicts_with_public_port")
        runtime = PrivateListenerRuntime(app, cfg)
        app.state.handoff_listener_runtime = runtime
        await runtime.start()
        return runtime
    except (HandoffDenied, OSError, ValueError, SystemExit):
        if runtime is not None:
            await runtime.stop()
        app.state.handoff_listener_runtime = None
        app.state.handoff_listener_status = "FAILED_CONFIG_OR_BIND"
        _LOG.warning("SRAF handoff disabled: configuration or listener unavailable")
        return None
    except BaseException:
        # Unexpected programming faults remain errors, but never leak sockets.
        if runtime is not None:
            await runtime.stop()
        raise
