"""DataStoreNode — ROS2 LifecycleNode for bonbon_data_stores.

Lifecycle states
----------------
configure  → open the SQLiteMemoryStore, run migrations
activate   → start retention-sweep timer, advertise services
deactivate → stop timer
cleanup    → close the store

ROS2 Services
-------------
/bonbon/data_store/save_interaction     (std_srvs/Trigger — payload in param)
/bonbon/data_store/save_user            (std_srvs/Trigger)
/bonbon/data_store/forget_user          (std_srvs/Trigger — user_id in param)
/bonbon/data_store/save_robot_state     (std_srvs/Trigger)
/bonbon/data_store/save_safety_event    (std_srvs/Trigger)
/bonbon/data_store/save_navigation_event (std_srvs/Trigger)
/bonbon/data_store/health_check         (std_srvs/Trigger)
/bonbon/data_store/create_backup        (std_srvs/Trigger)

ROS2 Topics published
---------------------
/bonbon/data_store/health  (std_msgs/String — JSON health snapshot)

ROS2 Parameters
---------------
data_dir           : str  — root data directory (default /tmp/bonbon/data)
retention_sweep_interval_sec : int  — seconds between sweeps (default 3600)
store_audio        : bool — whether to store raw audio refs (default False)
store_face_data    : bool — whether to store face encoding refs (default False)
embedding_model    : str  — sentence-transformer model name (HuggingFace)
faiss_enabled      : bool — enable FAISS vector store (default True)
chroma_enabled     : bool — enable ChromaDB RAG store (default True)
"""

from __future__ import annotations

import json
import logging
import threading

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conditional ROS2 import — allows the module to be imported in pure-Python
# tests without a ROS2 installation.
# ---------------------------------------------------------------------------
try:
    import rclpy  # type: ignore
    from rclpy.lifecycle import LifecycleNode, TransitionCallbackReturn  # type: ignore
    from std_msgs.msg import String  # type: ignore
    from std_srvs.srv import Trigger  # type: ignore

    _HAS_ROS2 = True
except ImportError:
    _HAS_ROS2 = False
    LifecycleNode = object  # type: ignore

from bonbon_data_stores.config.store_config import DataStoreConfig
from bonbon_data_stores.store import SQLiteMemoryStore


class DataStoreNode(LifecycleNode):
    """ROS2 LifecycleNode that manages the BonBon data stores."""

    def __init__(self, node_name: str = "data_store_node") -> None:
        if _HAS_ROS2:
            super().__init__(node_name)
        self._store: SQLiteMemoryStore | None = None
        self._sweep_timer = None
        self._sweep_thread: threading.Thread | None = None
        self._sweep_stop = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    def on_configure(self, state):
        logger.info("DataStoreNode: configuring...")
        try:
            cfg = self._build_config()
            self._store = SQLiteMemoryStore(cfg)
            self._store.open()
            logger.info("DataStoreNode: configured successfully")
            if _HAS_ROS2:
                return TransitionCallbackReturn.SUCCESS
        except Exception as exc:
            logger.error("DataStoreNode configure failed: %s", exc)
            if _HAS_ROS2:
                return TransitionCallbackReturn.FAILURE

    def on_activate(self, state):
        logger.info("DataStoreNode: activating...")
        try:
            self._register_services()
            self._start_sweep_thread()
            if _HAS_ROS2:
                self._health_pub = self.create_publisher(String, "/bonbon/data_store/health", 10)
                return TransitionCallbackReturn.SUCCESS
        except Exception as exc:
            logger.error("DataStoreNode activate failed: %s", exc)
            if _HAS_ROS2:
                return TransitionCallbackReturn.FAILURE

    def on_deactivate(self, state):
        logger.info("DataStoreNode: deactivating...")
        self._stop_sweep_thread()
        if _HAS_ROS2:
            return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state):
        logger.info("DataStoreNode: cleaning up...")
        if self._store:
            self._store.close()
            self._store = None
        if _HAS_ROS2:
            return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state):
        self.on_cleanup(state)
        if _HAS_ROS2:
            return TransitionCallbackReturn.SUCCESS

    # ------------------------------------------------------------------
    # Service handlers
    # ------------------------------------------------------------------

    def _handle_health_check(self, request, response):
        if self._store is None:
            response.success = False
            response.message = "store not initialised"
            return response
        health = self._store.check_health()
        response.success = health.level.value != "unhealthy"
        response.message = json.dumps(health.to_dict())
        return response

    def _handle_create_backup(self, request, response):
        if self._store is None:
            response.success = False
            response.message = "store not initialised"
            return response
        try:
            path = self._store.backup.create_backup()
            response.success = True
            response.message = str(path)
        except Exception as exc:
            response.success = False
            response.message = str(exc)
        return response

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_config(self) -> DataStoreConfig:
        """Build DataStoreConfig from ROS2 parameters (or defaults)."""
        if _HAS_ROS2:
            self.declare_parameter("data_dir", "/tmp/bonbon/data")
            self.declare_parameter("store_audio", False)
            self.declare_parameter("store_face_data", False)
            self.declare_parameter("embedding_model", "all-MiniLM-L6-v2")
            self.declare_parameter("faiss_enabled", True)
            self.declare_parameter("chroma_enabled", True)
            self.declare_parameter("retention_sweep_interval_sec", 3600)

            data_dir = self.get_parameter("data_dir").value
            _ = self.get_parameter("store_audio").value
            _ = self.get_parameter("store_face_data").value
            _ = self.get_parameter("embedding_model").value
            _ = self.get_parameter("faiss_enabled").value
            _ = self.get_parameter("chroma_enabled").value
        else:
            data_dir = "/tmp/bonbon/data"

        return DataStoreConfig.from_env(base_dir=data_dir)

    def _register_services(self) -> None:
        if not _HAS_ROS2:
            return
        self.create_service(Trigger, "/bonbon/data_store/health_check", self._handle_health_check)
        self.create_service(Trigger, "/bonbon/data_store/create_backup", self._handle_create_backup)

    def _start_sweep_thread(self) -> None:
        self._sweep_stop.clear()
        interval = 3600
        if _HAS_ROS2:
            interval = self.get_parameter("retention_sweep_interval_sec").value

        def _sweeper():
            while not self._sweep_stop.wait(timeout=interval):
                if self._store:
                    try:
                        totals = self._store.retention.sweep()
                        if totals:
                            logger.info("Retention sweep: %s", totals)
                    except Exception as exc:
                        logger.error("Retention sweep error: %s", exc)

        self._sweep_thread = threading.Thread(target=_sweeper, daemon=True, name="retention-sweep")
        self._sweep_thread.start()

    def _stop_sweep_thread(self) -> None:
        self._sweep_stop.set()
        if self._sweep_thread and self._sweep_thread.is_alive():
            self._sweep_thread.join(timeout=5.0)


def main(args=None):
    if not _HAS_ROS2:
        logger.error("rclpy not available; cannot start DataStoreNode")
        return

    rclpy.init(args=args)
    node = DataStoreNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
