"""KioskAPIServer — FastAPI application factory and lifecycle management.

Usage
-----
Standalone (development):
    uvicorn bonbon_patient_kiosk.main:create_app --factory --reload

From ROS2 node:
    server = KioskAPIServer(config)
    server.start()   # launches uvicorn in background thread
    server.stop()
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from bonbon_patient_kiosk.api.appointment_api import appointment_router
from bonbon_patient_kiosk.api.auth_api import auth_router
from bonbon_patient_kiosk.api.chat_api import chat_router
from bonbon_patient_kiosk.api.consent_api import consent_router
from bonbon_patient_kiosk.api.dashboard_api import dashboard_router
from bonbon_patient_kiosk.api.facility_map_api import facility_map_router
from bonbon_patient_kiosk.api.feedback_api import feedback_router
from bonbon_patient_kiosk.api.intake_api import intake_router
from bonbon_patient_kiosk.api.navigation_api import navigation_router
from bonbon_patient_kiosk.api.panic_api import panic_router
from bonbon_patient_kiosk.api.patient_lookup_api import patient_lookup_router
from bonbon_patient_kiosk.api.queue_api import queue_router
from bonbon_patient_kiosk.api.session_api import session_router
from bonbon_patient_kiosk.audit.audit_logger import AuditLogger
from bonbon_patient_kiosk.auth.auth_manager import AuthManager
from bonbon_patient_kiosk.auth.role_permissions import RolePermissionManager
from bonbon_patient_kiosk.config.kiosk_api_config import KioskAPIConfig
from bonbon_patient_kiosk.data.adapters.emr_adapter import MockEMRAdapter
from bonbon_patient_kiosk.data.adapters.notifier_adapter import MockNotifierAdapter
from bonbon_patient_kiosk.data.adapters.scheduling_adapter import MockSchedulingAdapter
from bonbon_patient_kiosk.data.crypto import PHICipher
from bonbon_patient_kiosk.data.facility_store import FacilityLabelStore
from bonbon_patient_kiosk.data.retention import run_purge
from bonbon_patient_kiosk.data.session_store import SessionStore
from bonbon_patient_kiosk.data.store import PatientDataStore
from bonbon_patient_kiosk.models.response_models import APIResponse
from bonbon_patient_kiosk.ros2.ros2_bridge import KioskROS2Bridge
from bonbon_patient_kiosk.safety.command_validator import CommandValidator
from bonbon_patient_kiosk.safety.kiosk_safety_gate import KioskSafetyGate

logger = logging.getLogger(__name__)

_SESSION_PURGE_INTERVAL_SEC = 30.0


def _build_app(cfg: KioskAPIConfig) -> FastAPI:
    # ------------------------------------------------------------------ #
    # Shared services                                                    #
    # ------------------------------------------------------------------ #
    audit_logger = AuditLogger(db_path=cfg.audit.db_path, max_events=cfg.audit.max_events)
    auth_manager = AuthManager(
        db_path=cfg.staff_users_db_path,
        jwt_secret=cfg.jwt.secret,
        algorithm=cfg.jwt.algorithm,
        token_expire_minutes=cfg.jwt.token_expire_minutes,
    )
    role_manager = RolePermissionManager()
    session_store = SessionStore(
        idle_timeout_sec=cfg.session.idle_timeout_sec,
        max_session_age_sec=cfg.session.max_session_age_sec,
    )
    cipher = PHICipher(cfg.encryption.key_hex)
    patient_store = PatientDataStore(db_path=cfg.patient_data_db_path, cipher=cipher)
    facility_label_store = FacilityLabelStore(path=cfg.facility_labels_path)

    emr_adapter = MockEMRAdapter()
    scheduling_adapter = MockSchedulingAdapter()
    notifier_adapter = MockNotifierAdapter()

    validator = CommandValidator(dedup_window_sec=5.0, dedup_capacity=256)
    kiosk_safety_gate = KioskSafetyGate(validator=validator, audit_logger=audit_logger)

    bridge = KioskROS2Bridge(
        navigate_timeout_sec=cfg.ros2.navigate_timeout_sec,
        llm_query_timeout_sec=cfg.ros2.llm_query_timeout_sec,
    )

    # ------------------------------------------------------------------ #
    # Lifespan (startup / shutdown)                                     #
    # ------------------------------------------------------------------ #

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if cfg.ros2.enabled:
            bridge.start()
            logger.info("Kiosk ROS2 bridge started")

        session_purge_task = asyncio.create_task(_session_purge_loop(session_store))
        retention_task = asyncio.create_task(
            _retention_loop(patient_store, cfg.retention.intake_retention_days, cfg.retention.purge_check_interval_sec)
        )

        logger.info("BonBon Patient Kiosk API ready — host=%s port=%d", cfg.server.host, cfg.server.port)
        yield

        session_purge_task.cancel()
        retention_task.cancel()
        if cfg.ros2.enabled:
            bridge.stop()
        logger.info("BonBon Patient Kiosk API shutdown complete")

    # ------------------------------------------------------------------ #
    # App factory                                                        #
    # ------------------------------------------------------------------ #
    app = FastAPI(
        title="BonBon Patient Kiosk API",
        description=(
            "Patient-facing REST API for the BonBon service robot's hospital "
            "reception deployment: intake, appointments, queue tokens, "
            "RAG-grounded chat/wayfinding, and a staff-only facility map "
            "editor. Every navigation/panic request is safety-gated exactly "
            "like the staff operator dashboard's commands."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors.allowed_origins,
        allow_credentials=cfg.cors.allow_credentials,
        allow_methods=cfg.cors.allowed_methods,
        allow_headers=cfg.cors.allowed_headers,
    )

    app.state.cfg = cfg
    app.state.audit_logger = audit_logger
    app.state.auth_manager = auth_manager
    app.state.role_manager = role_manager
    app.state.session_store = session_store
    app.state.patient_store = patient_store
    app.state.facility_label_store = facility_label_store
    app.state.emr_adapter = emr_adapter
    app.state.scheduling_adapter = scheduling_adapter
    app.state.notifier_adapter = notifier_adapter
    app.state.kiosk_safety_gate = kiosk_safety_gate
    app.state.ros2_bridge = bridge

    app.include_router(session_router, prefix="/api/v1")
    app.include_router(consent_router, prefix="/api/v1")
    app.include_router(patient_lookup_router, prefix="/api/v1")
    app.include_router(intake_router, prefix="/api/v1")
    app.include_router(appointment_router, prefix="/api/v1")
    app.include_router(queue_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(navigation_router, prefix="/api/v1")
    app.include_router(panic_router, prefix="/api/v1")
    app.include_router(feedback_router, prefix="/api/v1")
    app.include_router(facility_map_router, prefix="/api/v1")
    app.include_router(dashboard_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")

    @app.get("/", include_in_schema=False)
    async def root():
        return {"service": "BonBon Patient Kiosk API", "version": "0.1.0", "docs": "/docs"}

    @app.get("/health", tags=["system"])
    async def health(request: Request):
        return {
            "status": "ok",
            "ros2_bridge_ready": request.app.state.ros2_bridge._ready(),
            "timestamp": time.time(),
        }

    @app.exception_handler(Exception)
    async def _global_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content=APIResponse.fail("An internal error occurred").model_dump())

    return app


async def _session_purge_loop(session_store: SessionStore) -> None:
    while True:
        try:
            await asyncio.sleep(_SESSION_PURGE_INTERVAL_SEC)
            purged = session_store.purge_idle()
            if purged:
                logger.info("Purged %d idle session(s)", len(purged))
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("Session purge loop error: %s", exc)


async def _retention_loop(store: PatientDataStore, retention_days: int, interval_sec: float) -> None:
    while True:
        try:
            await asyncio.sleep(interval_sec)
            run_purge(store, retention_days)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("Retention loop error: %s", exc)


# ---------------------------------------------------------------------------
# Public factory function
# ---------------------------------------------------------------------------


def create_app(config: KioskAPIConfig | None = None) -> FastAPI:
    cfg = config or KioskAPIConfig()
    return _build_app(cfg)


# ---------------------------------------------------------------------------
# KioskAPIServer — wraps uvicorn for use from the ROS2 node
# ---------------------------------------------------------------------------


class KioskAPIServer:
    def __init__(self, config: KioskAPIConfig) -> None:
        self._cfg = config
        self._thread: threading.Thread | None = None
        self._server = None

    def start(self) -> None:
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
        self._thread = threading.Thread(target=self._server.run, daemon=True, name="kiosk-api-uvicorn")
        self._thread.start()
        logger.info("KioskAPIServer started on %s:%d", self._cfg.server.host, self._cfg.server.port)

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        logger.info("KioskAPIServer stopped")


def run_server() -> None:
    """Entry point for the ``kiosk_api_server`` console script."""
    import uvicorn

    cfg = KioskAPIConfig()
    app = create_app(cfg)
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_level=cfg.server.log_level.lower())
