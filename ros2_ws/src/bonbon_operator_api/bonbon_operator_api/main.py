"""OperatorAPIServer — FastAPI application factory and lifecycle management.

Usage
-----
Standalone (development):
    uvicorn bonbon_operator_api.main:create_app --factory --reload

From ROS2 node:
    server = OperatorAPIServer(config)
    server.start()   # launches uvicorn in background thread
    server.stop()
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from bonbon_operator_api.api.auth_api import auth_router
from bonbon_operator_api.api.command_api import cmd_router
from bonbon_operator_api.api.config_api import config_router, _ConfigStore
from bonbon_operator_api.api.diagnostics_api import diag_router
from bonbon_operator_api.api.llm_test_api import llm_router
from bonbon_operator_api.api.memory_api import memory_router
from bonbon_operator_api.api.robot_status_api import status_router
from bonbon_operator_api.audit.audit_logger import AuditLogger
from bonbon_operator_api.auth.auth_manager import AuthManager
from bonbon_operator_api.auth.role_permissions import RolePermissionManager
from bonbon_operator_api.config.api_config import OperatorAPIConfig
from bonbon_operator_api.metrics.metrics_collector import DashboardMetricsCollector
from bonbon_operator_api.models.response_models import APIResponse
from bonbon_operator_api.ros2.ros2_bridge import ROS2DashboardBridge
from bonbon_operator_api.ros2.status_aggregator import RobotStatusAggregator
from bonbon_operator_api.safety.command_validator import CommandValidator
from bonbon_operator_api.safety.safety_gate import SafetyCommandGate
from bonbon_operator_api.websocket.ws_manager import WebSocketConnectionManager
from bonbon_operator_api.websocket.ws_router import ws_router

logger = logging.getLogger(__name__)

# How often the status broadcaster sends snapshots to WebSocket clients (seconds)
_STATUS_BROADCAST_INTERVAL = 1.0


def _build_app(cfg: OperatorAPIConfig) -> FastAPI:
    """Construct and configure the FastAPI application."""

    # ------------------------------------------------------------------ #
    # Shared services                                                       #
    # ------------------------------------------------------------------ #
    audit_logger = AuditLogger(
        db_path=cfg.audit.db_path,
        max_events=cfg.audit.max_events,
    )
    auth_manager = AuthManager(
        db_path=cfg.users_db_path,
        jwt_secret=cfg.jwt.secret,
        algorithm=cfg.jwt.algorithm,
        token_expire_minutes=cfg.jwt.token_expire_minutes,  # matches JWTConfig field
    )
    role_manager = RolePermissionManager()
    metrics = DashboardMetricsCollector(enabled=cfg.metrics.enabled)

    aggregator = RobotStatusAggregator(
        offline_timeout_sec=cfg.ros2.offline_timeout_sec,
    )
    ws_manager = WebSocketConnectionManager()
    bridge = ROS2DashboardBridge(
        aggregator=aggregator,
        node_name="bonbon_dashboard_bridge",
    )
    validator = CommandValidator(
        dedup_window_sec=5.0,
        dedup_capacity=256,
    )
    safety_gate = SafetyCommandGate(
        validator=validator,
        status_aggregator=aggregator,
        audit_logger=audit_logger,
    )
    config_store = _ConfigStore(cfg.config_store_path)

    # ------------------------------------------------------------------ #
    # Lifespan (startup / shutdown)                                        #
    # ------------------------------------------------------------------ #

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        loop = asyncio.get_event_loop()
        event_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        bridge.set_event_queue(event_queue, loop)
        if cfg.ros2.enabled:
            bridge.start()
            logger.info("ROS2 bridge started")

        # Background task: event queue → WebSocket broadcast
        event_task = asyncio.create_task(_event_dispatcher(event_queue, ws_manager))

        # Background task: periodic status broadcast
        status_task = asyncio.create_task(
            _status_broadcaster(aggregator, ws_manager, metrics)
        )

        logger.info(
            "BonBon Operator API ready — host=%s port=%d",
            cfg.server.host, cfg.server.port,
        )
        yield

        # Shutdown
        event_task.cancel()
        status_task.cancel()
        if cfg.ros2.enabled:
            bridge.stop()
        logger.info("BonBon Operator API shutdown complete")

    # ------------------------------------------------------------------ #
    # App factory                                                          #
    # ------------------------------------------------------------------ #
    app = FastAPI(
        title="BonBon Operator API",
        description=(
            "REST + WebSocket dashboard API for the BonBon service robot. "
            "Every command is gated through the Safety Supervisor."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors.allowed_origins,      # CORSConfig field
        allow_credentials=cfg.cors.allow_credentials,
        allow_methods=cfg.cors.allowed_methods,
        allow_headers=cfg.cors.allowed_headers,
    )

    # Store shared services on app state
    app.state.cfg = cfg
    app.state.audit_logger = audit_logger
    app.state.auth_manager = auth_manager
    app.state.role_manager = role_manager
    app.state.metrics = metrics
    app.state.status_aggregator = aggregator
    app.state.ws_manager = ws_manager
    app.state.ros2_bridge = bridge
    app.state.safety_gate = safety_gate
    app.state.config_store = config_store

    # Routers
    app.include_router(auth_router,   prefix="/api/v1")
    app.include_router(status_router, prefix="/api/v1")
    app.include_router(cmd_router,    prefix="/api/v1")
    app.include_router(diag_router,   prefix="/api/v1")
    app.include_router(config_router, prefix="/api/v1")
    app.include_router(memory_router, prefix="/api/v1")
    app.include_router(llm_router,    prefix="/api/v1")
    app.include_router(ws_router)

    # ------------------------------------------------------------------ #
    # Extra routes                                                         #
    # ------------------------------------------------------------------ #

    @app.get("/", include_in_schema=False)
    async def root():
        return {"service": "BonBon Operator API", "version": "1.0.0", "docs": "/docs"}

    @app.get("/health", tags=["system"])
    async def health(request: Request):
        agg = request.app.state.status_aggregator
        return {
            "status": "ok",
            "robot_online": agg.is_online(),
            "timestamp": time.time(),
        }

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics(request: Request):
        m: DashboardMetricsCollector = request.app.state.metrics
        content, content_type = m.generate_text()
        return Response(content=content, media_type=content_type)

    # Global error handler — never expose raw internal tracebacks
    @app.exception_handler(Exception)
    async def _global_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=APIResponse.fail("An internal error occurred").model_dump(),
        )

    return app


async def _event_dispatcher(
    queue: asyncio.Queue,
    ws_manager: WebSocketConnectionManager,
) -> None:
    """Consume events from the ROS2 bridge and broadcast to WS clients."""
    while True:
        try:
            msg = await queue.get()
            channel = msg.get("channel", "robot-status")
            event = msg.get("event", "update")
            data = msg.get("data", {})
            await ws_manager.broadcast(channel, event, data)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("Event dispatcher error: %s", exc)


async def _status_broadcaster(
    aggregator: RobotStatusAggregator,
    ws_manager: WebSocketConnectionManager,
    metrics: DashboardMetricsCollector,
) -> None:
    """Periodically broadcast a full status snapshot to all robot-status subscribers."""
    while True:
        try:
            await asyncio.sleep(_STATUS_BROADCAST_INTERVAL)
            status = aggregator.get_status()
            snapshot = status.model_dump()
            await ws_manager.broadcast("robot-status", "status_update", snapshot)
            # Update Prometheus gauges
            metrics.update_robot_state(
                is_online=status.is_online,
                battery_pct=status.battery.percentage,
            )
            metrics.update_ws_connections(ws_manager.connection_counts())
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("Status broadcaster error: %s", exc)


# ---------------------------------------------------------------------------
# Public factory function (used by uvicorn --factory and ROS2 node)
# ---------------------------------------------------------------------------

def create_app(config: Optional[OperatorAPIConfig] = None) -> FastAPI:
    """FastAPI application factory.

    Parameters
    ----------
    config:
        ``OperatorAPIConfig`` instance.  If None, a default config is
        constructed from environment variables.
    """
    cfg = config or OperatorAPIConfig()
    return _build_app(cfg)


# ---------------------------------------------------------------------------
# OperatorAPIServer — wraps uvicorn for use from the ROS2 node
# ---------------------------------------------------------------------------

class OperatorAPIServer:
    """Launch and manage the FastAPI server in a background thread.

    Parameters
    ----------
    config:
        ``OperatorAPIConfig`` with all server settings.
    """

    def __init__(self, config: OperatorAPIConfig) -> None:
        self._cfg = config
        self._thread: Optional[threading.Thread] = None
        self._server = None

    def start(self) -> None:
        """Start uvicorn in a daemon thread."""
        import uvicorn

        app = create_app(self._cfg)
        uv_config = uvicorn.Config(
            app=app,
            host=self._cfg.server.host,
            port=self._cfg.server.port,
            log_level=self._cfg.server.log_level.lower(),
            access_log=False,
        )
        self._server = uvicorn.Server(uv_config)
        self._thread = threading.Thread(
            target=self._server.run,
            daemon=True,
            name="operator-api-uvicorn",
        )
        self._thread.start()
        logger.info(
            "OperatorAPIServer started on %s:%d",
            self._cfg.server.host, self._cfg.server.port,
        )

    def stop(self) -> None:
        """Gracefully stop uvicorn."""
        if self._server:
            self._server.should_exit = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        logger.info("OperatorAPIServer stopped")


def run_server() -> None:
    """Entry point for ``operator_api_server`` console script."""
    import uvicorn
    cfg = OperatorAPIConfig()
    app = create_app(cfg)
    uvicorn.run(
        app,
        host=cfg.server.host,
        port=cfg.server.port,
        log_level=cfg.server.log_level.lower(),
    )
