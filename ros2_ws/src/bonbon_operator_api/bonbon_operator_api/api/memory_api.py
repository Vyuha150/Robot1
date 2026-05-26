"""Memory and RAG API — query bonbon_data_stores via the ROS2 bridge.

Read access: engineer+
Write access: admin only
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from bonbon_operator_api.auth.dependencies import get_current_user, require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.response_models import APIResponse

logger = logging.getLogger(__name__)

memory_router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=100)


class RAGQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    collection: str = Field(default="general_knowledge")
    top_k: int = Field(default=5, ge=1, le=20)


@memory_router.post("/query", response_model=APIResponse)
async def query_memory(
    request: Request,
    body: MemoryQueryRequest,
    current_user: TokenPayload = Depends(require_permission("memory:read")),
) -> APIResponse:
    """Query the episodic memory store."""
    bridge = request.app.state.ros2_bridge
    result = bridge.call_memory_query(body.query, body.limit)
    if not result.get("success", True):
        raise HTTPException(status_code=503, detail="Memory query failed")
    return APIResponse.ok(result)


@memory_router.post("/rag/query", response_model=APIResponse)
async def query_rag(
    request: Request,
    body: RAGQueryRequest,
    current_user: TokenPayload = Depends(require_permission("rag:query")),
) -> APIResponse:
    """Query the RAG (ChromaDB) knowledge base."""
    bridge = request.app.state.ros2_bridge
    result = bridge.call_rag_query(body.query, body.collection, body.top_k)
    if not result.get("success", True):
        raise HTTPException(status_code=503, detail="RAG query failed")
    return APIResponse.ok(result)
