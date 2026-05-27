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
    LogInfo,
)
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import LifecycleNode


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

    return LaunchDescription(args + [startup_log, llm_node])
