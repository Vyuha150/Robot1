"""
bonbon_llm.core
===============
Core LLM + RAG infrastructure.

Lazy-import contract
--------------------
* ``OllamaClient``, ``RAGRetriever``, ``ResponseLogger`` — always importable.
* ``LangChainBridge`` components — raise ``LangChainUnavailableError`` when
  langchain is not installed; the node degrades gracefully.
"""
from bonbon_llm.core.ollama_client import OllamaClient, OllamaResponse
from bonbon_llm.core.rag_retriever import RAGRetriever, RAGDocument, RetrievalResult
from bonbon_llm.core.response_logger import ResponseLogger, LogEntry
from bonbon_llm.core.langchain_bridge import LangChainUnavailableError

__all__ = [
    # Ollama
    "OllamaClient",
    "OllamaResponse",
    # RAG
    "RAGRetriever",
    "RAGDocument",
    "RetrievalResult",
    # Logger
    "ResponseLogger",
    "LogEntry",
    # LangChain
    "LangChainUnavailableError",
]
