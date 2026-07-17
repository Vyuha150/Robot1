"""
bonbon_llm — ROS2 launch file
==============================
Launches the LLM Orchestrator LifecycleNode with all configurable parameters
exposed as launch arguments so they can be overridden on the command line
or composed into a larger system launch.

Usage examples
--------------
# Minimal — uses all defaults (Ollama at localhost:11434, llama3.2:3b)
ros2 launch bonbon_llm llm.launch.py

# Override model and RAG backend
ros2 launch bonbon_llm llm.launch.py ollama_model:=mistral:7b rag_backend:=faiss

# Simulation mode with verbose logging
ros2 launch bonbon_llm llm.launch.py simulation:=true log_level:=debug
"""

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    LogInfo,
    RegisterEventHandler,
)
from launch.event_handlers import OnProcessStart
from launch.events import matches_action
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import LifecycleNode
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition


def generate_launch_description() -> LaunchDescription:

    # ── Launch arguments ──────────────────────────────────────────────────────

    args = [
        # --- Ollama / LLM ---
        DeclareLaunchArgument(
            "ollama_base_url",
            default_value="http://localhost:11434",
            description="Base URL for the local Ollama server",
        ),
        DeclareLaunchArgument(
            "ollama_model",
            default_value="llama3.2:3b",
            description="Ollama model name (must be pulled: ollama pull <model>)",
        ),
        DeclareLaunchArgument(
            "ollama_timeout",
            default_value="30.0",
            description="Ollama request timeout in seconds",
        ),
        DeclareLaunchArgument(
            "ollama_temperature",
            default_value="0.4",
            description="Sampling temperature (0=deterministic, 1=creative)",
        ),
        DeclareLaunchArgument(
            "ollama_max_tokens",
            default_value="256",
            description="Maximum tokens in LLM response",
        ),
        # --- RAG ---
        DeclareLaunchArgument(
            "rag_backend",
            default_value="chroma",
            description="RAG vector store backend: 'chroma', 'faiss', or 'numpy'",
        ),
        DeclareLaunchArgument(
            "rag_top_k",
            default_value="5",
            description="Number of RAG documents to retrieve per query",
        ),
        DeclareLaunchArgument(
            "rag_similarity_threshold",
            default_value="0.35",
            description="Minimum cosine similarity for a RAG result to be used",
        ),
        DeclareLaunchArgument(
            "rag_persist_dir",
            default_value="",
            description="ChromaDB persistence directory (empty = in-memory only)",
        ),
        DeclareLaunchArgument(
            "rag_collection_name",
            default_value="bonbon_kb",
            description="ChromaDB collection name",
        ),
        # --- Hallucination guard ---
        DeclareLaunchArgument(
            "hallucination_guard_enabled",
            default_value="true",
            description="Enable hallucination / grounding checks",
        ),
        DeclareLaunchArgument(
            "min_grounding_score",
            default_value="0.30",
            description="Minimum keyword-overlap grounding score (0–1)",
        ),
        # --- Safety filter ---
        DeclareLaunchArgument(
            "min_risky_confidence",
            default_value="0.80",
            description="Min LLM confidence to allow a RISKY command through",
        ),
        # --- Pi-2 LLM guard (Pi2LLMGuardConfig in llm_config.py) -- CPU/thermal
        # self-protection for a tiny local model on shared, resource-limited
        # Pi-2 hardware. Previously built and read via from_ros_params() but
        # never exposed here at all, so it was unreachable through this launch
        # file no matter what a Pi-2 deployment profile wanted -- same class
        # of bug as bonbon_human_ai_bringup's missing vision/speech backend
        # pass-through. Disabled by default (enabled=false), matching
        # Pi2LLMGuardConfig's own default -- a Pi-2 runtime profile must
        # explicitly turn it on.
        DeclareLaunchArgument(
            "pi2_guard_enabled",
            default_value="false",
            description="Enable Pi-2 CPU/thermal self-protection guard for local LLM calls",
        ),
        DeclareLaunchArgument(
            "pi2_guard_max_concurrent_requests",
            default_value="1",
            description="Max concurrent local LLM inferences (bounds CPU/memory on Pi-2)",
        ),
        DeclareLaunchArgument(
            "pi2_guard_max_output_tokens",
            default_value="64",
            description="Max output tokens per response when the guard is active",
        ),
        DeclareLaunchArgument(
            "pi2_guard_initial_timeout_sec",
            default_value="1.0",
            description="Initial per-request timeout before the guard escalates",
        ),
        DeclareLaunchArgument(
            "pi2_guard_cpu_disable_threshold_percent",
            default_value="85.0",
            description="Disable local LLM calls above this CPU percent",
        ),
        DeclareLaunchArgument(
            "pi2_guard_temp_disable_threshold_c",
            default_value="75.0",
            description="Disable local LLM calls above this CPU temperature (Celsius)",
        ),
        # --- Personality ---
        DeclareLaunchArgument(
            "robot_name",
            default_value="BonBon",
            description="Robot's spoken name used in responses",
        ),
        DeclareLaunchArgument(
            "max_response_words",
            default_value="40",
            description="Maximum words per TTS response",
        ),
        # --- Pipeline ---
        DeclareLaunchArgument(
            "min_confidence_threshold",
            default_value="0.45",
            description="Minimum LLM confidence before using fallback response",
        ),
        DeclareLaunchArgument(
            "use_langchain",
            default_value="true",
            description="Attempt to use LangChain chain; falls back to Ollama direct if unavailable",
        ),
        DeclareLaunchArgument(
            "use_tools",
            default_value="true",
            description="Enable OpenAI-compatible tool/function calling",
        ),
        DeclareLaunchArgument(
            "use_rag",
            default_value="true",
            description="Enable RAG retrieval for knowledge grounding",
        ),
        # --- Node ---
        DeclareLaunchArgument(
            "namespace",
            default_value="",
            description="ROS2 namespace for this node",
        ),
        DeclareLaunchArgument(
            "log_level",
            default_value="info",
            description="Logging level: debug, info, warn, error",
        ),
        DeclareLaunchArgument(
            "simulation",
            default_value="false",
            description="Simulation mode — disables real Ollama calls for CI/testing",
        ),
    ]

    # ── Node parameters ───────────────────────────────────────────────────────

    node_params = [
        # Ollama
        {"ollama.base_url": LaunchConfiguration("ollama_base_url")},
        {"ollama.model": LaunchConfiguration("ollama_model")},
        {"ollama.timeout_sec": LaunchConfiguration("ollama_timeout")},
        {"ollama.temperature": LaunchConfiguration("ollama_temperature")},
        {"ollama.max_tokens": LaunchConfiguration("ollama_max_tokens")},
        # RAG
        {"rag.backend": LaunchConfiguration("rag_backend")},
        {"rag.top_k": LaunchConfiguration("rag_top_k")},
        {"rag.similarity_threshold": LaunchConfiguration("rag_similarity_threshold")},
        {"rag.persist_dir": LaunchConfiguration("rag_persist_dir")},
        {"rag.collection_name": LaunchConfiguration("rag_collection_name")},
        # Hallucination guard
        {"hallucination.enabled": LaunchConfiguration("hallucination_guard_enabled")},
        {"hallucination.min_grounding_score": LaunchConfiguration("min_grounding_score")},
        # Safety filter
        {"safety_filter.min_risky_confidence": LaunchConfiguration("min_risky_confidence")},
        # Pi-2 LLM guard
        {"pi2_guard.enabled": LaunchConfiguration("pi2_guard_enabled")},
        {
            "pi2_guard.max_concurrent_requests": LaunchConfiguration(
                "pi2_guard_max_concurrent_requests"
            )
        },
        {"pi2_guard.max_output_tokens": LaunchConfiguration("pi2_guard_max_output_tokens")},
        {"pi2_guard.initial_timeout_sec": LaunchConfiguration("pi2_guard_initial_timeout_sec")},
        {
            "pi2_guard.cpu_disable_threshold_percent": LaunchConfiguration(
                "pi2_guard_cpu_disable_threshold_percent"
            )
        },
        {
            "pi2_guard.temp_disable_threshold_c": LaunchConfiguration(
                "pi2_guard_temp_disable_threshold_c"
            )
        },
        # Personality
        {"personality.name": LaunchConfiguration("robot_name")},
        {"personality.max_response_words": LaunchConfiguration("max_response_words")},
        # Pipeline
        {"min_confidence_threshold": LaunchConfiguration("min_confidence_threshold")},
        {"use_langchain": LaunchConfiguration("use_langchain")},
        {"use_tools": LaunchConfiguration("use_tools")},
        {"use_rag": LaunchConfiguration("use_rag")},
        # Node
        {"simulation": LaunchConfiguration("simulation")},
        {"use_sim_time": LaunchConfiguration("simulation")},
    ]

    # ── Lifecycle node ────────────────────────────────────────────────────────

    llm_node = LifecycleNode(
        package="bonbon_llm",
        executable="llm_orchestrator_node",
        name="llm_orchestrator",
        namespace=LaunchConfiguration("namespace"),
        parameters=node_params,
        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
        output="screen",
        emulate_tty=True,
    )

    startup_log = LogInfo(
        msg=PythonExpression(
            [
                "'[bonbon_llm] Starting LLMOrchestratorNode — model: '",
                " + '",
                LaunchConfiguration("ollama_model"),
                "'",
                " + ', rag: '",
                " + '",
                LaunchConfiguration("rag_backend"),
                "'",
            ]
        )
    )

    # ── Auto configure -> activate ───────────────────────────────────────────
    # llm_node previously had no mechanism transitioning it out of
    # "unconfigured" at all -- unlike every other LifecycleNode launch file
    # in this repo (tts, speech, vision, perception, ...), this file never
    # emitted a CONFIGURE/ACTIVATE event, so llm_orchestrator_node sat idle
    # forever after creation. Confirmed on real Pi-2 hardware: the node logs
    # "LLMOrchestratorNode created" and nothing else, indefinitely.
    configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=matches_action(llm_node),
            transition_id=Transition.TRANSITION_CONFIGURE,
        )
    )
    activate_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=matches_action(llm_node),
            transition_id=Transition.TRANSITION_ACTIVATE,
        )
    )
    on_start_configure = RegisterEventHandler(
        OnProcessStart(
            target_action=llm_node,
            on_start=[
                LogInfo(msg="LLMOrchestratorNode started — sending configure transition"),
                configure_event,
            ],
        )
    )
    on_configured_activate = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=llm_node,
            goal_state="inactive",
            entities=[
                LogInfo(msg="LLMOrchestratorNode inactive — sending activate transition"),
                activate_event,
            ],
        )
    )

    return LaunchDescription(
        args + [startup_log, llm_node, on_start_configure, on_configured_activate]
    )
