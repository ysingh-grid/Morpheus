"""OpenAI-compatible HTTP gateway for the durable RAG agent workflow."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

from urllib.parse import quote, unquote

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from langsmith import traceable
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError

from ingestion.doc_processor import document_id_for_file, process_document
from orchestration.workflows import DocumentIngestionWorkflow
from retrieval.pg_engine import (
    attach_documents_to_session,
    document_ingestion_stats,
    get_document_source_path,
    get_figure_image_data,
    ingest_bundle,
)
from security import guardrails


logger = logging.getLogger(__name__)

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TASK_QUEUE = "rag-agent-queue"
MODEL_ID = "local-rag-agent"
WORKFLOW_TYPE = "AgentWorkflow"
UPLOAD_DIRECTORY = Path(os.getenv("MORPHEUS_UPLOAD_DIR", "uploaded_documents"))
MAX_UPLOAD_FILES = int(os.getenv("MAX_UPLOAD_FILES", "10"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
INGESTION_BATCH_PREFIX = "ingest-batch-"
SINGLE_USER_ID = os.getenv("MORPHEUS_USER_ID", "usr_local")


def _resolve_user_id(requested_user: Any) -> str:
    """Resolve user identity, mapping empty or generic UI IDs to the single-user default."""
    if not isinstance(requested_user, str) or not requested_user.strip():
        return SINGLE_USER_ID
    cleaned = requested_user.strip()
    if cleaned in {"usr_openwebui", "usr_default"}:
        return SINGLE_USER_ID
    return cleaned


app = FastAPI(title="Morpheus OpenAI-Compatible API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "HEAD", "POST", "OPTIONS"],
    allow_headers=["*"],
)
UploadProgressCallback = Callable[[int, str, dict[str, Any]], None]


class ClarificationSignalRequest(BaseModel):
    """Validate a human decision before it reaches a Temporal workflow."""

    choice: Literal["approve_web_search", "cancel"]


class WorkflowStateResponse(BaseModel):
    """Expose the compact, durable state required by a polling UI."""

    workflow_id: str
    status: str
    user_choice: str | None = None
    final_answer: str = ""
    execution_history: list[str] = Field(default_factory=list)


class UploadedDocumentResult(BaseModel):
    """Describe one completed PDF ingestion performed through the HTTP gateway."""

    filename: str
    document_id: str
    status: Literal["ingested", "already_ingested"]
    parents: int
    children: int
    figures: int
    tables: int
    table_chunks: int


class DocumentUploadResponse(BaseModel):
    """Return the outcome of every PDF in a single multipart upload request."""

    status: Literal["completed"]
    documents: list[UploadedDocumentResult]


class DocumentUploadJobResponse(BaseModel):
    """Expose background PDF ingestion progress to polling user interfaces."""

    job_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    progress: int = Field(ge=0, le=100)
    stage: str
    details: dict[str, Any] = Field(default_factory=dict)
    documents: list[UploadedDocumentResult] = Field(default_factory=list)
    error: str | None = None


def _message_content(message: dict[str, Any]) -> str:
    """Validate and return one text OpenAI chat message content value."""
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(
            status_code=422,
            detail={
                "error": {"message": "Each message must have non-empty text content."}
            },
        )
    return content


_ALLOWED_MESSAGE_ROLES = frozenset({"user", "assistant", "system"})


def _message_role(message: dict[str, Any]) -> str:
    """Validate and return one supported OpenAI chat message role."""
    role = message.get("role")
    if not isinstance(role, str) or role not in _ALLOWED_MESSAGE_ROLES:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "message": "Each message role must be one of: user, assistant, system."
                }
            },
        )
    return role


@traceable(name="sanitize_messages", run_type="chain")
def _sanitize_messages(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Screen user turns for injection and only the current turn for safety."""
    if not messages:
        raise HTTPException(
            status_code=422,
            detail={"error": {"message": "At least one chat message is required."}},
        )

    validated_messages: list[tuple[dict[str, Any], str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            raise HTTPException(
                status_code=422,
                detail={"error": {"message": "Each message must be an object."}},
            )
        role = _message_role(message)
        content = _message_content(message)
        validated_messages.append((message, role, content))

    if validated_messages[-1][1] != "user":
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "message": "The final message in the chat conversation must be a user turn."
                }
            },
        )

    sanitized_messages: list[dict[str, Any]] = []
    latest_sanitized_query = ""
    final_message_index = len(validated_messages) - 1
    for index, (message, role, content) in enumerate(validated_messages):
        sanitized_message = dict(message)
        if role != "user":
            sanitized_message["content"] = guardrails.anonymize_pii(content)
            sanitized_messages.append(sanitized_message)
            continue

        scan_result = guardrails.scan_user_input(
            content,
            include_content_safety=index == final_message_index,
        )
        if not scan_result.is_safe:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "message": scan_result.flag_reason,
                        "type": "guardrail_violation",
                    }
                },
            )
        sanitized_message["content"] = scan_result.sanitized_prompt
        latest_sanitized_query = scan_result.sanitized_prompt
        sanitized_messages.append(sanitized_message)
    return latest_sanitized_query, sanitized_messages


def _workflow_id(user_id: str, session_id: str) -> str:
    """Create one unique workflow identity while retaining the chat scope in its name."""
    return f"wf-{user_id}-{session_id}-{uuid4().hex}"


async def _save_uploaded_pdf(upload: UploadFile) -> tuple[str, Path]:
    """Validate one PDF upload and persist it under an opaque local filename."""
    original_filename = Path(upload.filename or "document.pdf").name
    if not original_filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "message": "Only PDF uploads are supported.",
                    "type": "invalid_file",
                }
            },
        )
    contents = await upload.read(MAX_UPLOAD_BYTES + 1)
    await upload.close()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "error": {
                    "message": "Uploaded PDF exceeds the size limit.",
                    "type": "file_too_large",
                }
            },
        )
    if not contents.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "message": "Uploaded file is not a valid PDF.",
                    "type": "invalid_file",
                }
            },
        )

    upload_directory = UPLOAD_DIRECTORY / uuid4().hex
    upload_directory.mkdir(parents=True, exist_ok=True)
    saved_path = upload_directory / original_filename
    try:
        saved_path.write_bytes(contents)
    except OSError as error:
        logger.exception(
            "Unable to persist uploaded PDF", extra={"filename": original_filename}
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": "Unable to store uploaded PDF.",
                    "type": "storage_error",
                }
            },
        ) from error
    return original_filename, saved_path


def _ingestion_batch_id(workflow_ids: list[str]) -> str:
    """Encode child ingestion workflow IDs in one durable, stateless batch identifier."""
    encoded = base64.urlsafe_b64encode(
        json.dumps(workflow_ids, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return f"{INGESTION_BATCH_PREFIX}{encoded}"


def _batch_workflow_ids(job_id: str) -> list[str] | None:
    """Decode a gateway-created batch identifier without relying on process memory."""
    if not job_id.startswith(INGESTION_BATCH_PREFIX):
        return None
    try:
        encoded = job_id.removeprefix(INGESTION_BATCH_PREFIX).encode("ascii")
        values = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except (
        binascii.Error,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {"message": "Upload job was not found.", "type": "not_found"}
            },
        ) from error
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(value, str) and value for value in values)
    ):
        raise HTTPException(
            status_code=404,
            detail={
                "error": {"message": "Upload job was not found.", "type": "not_found"}
            },
        )
    return values


def _aggregate_ingestion_progress(
    job_id: str, child_states: list[dict[str, Any]]
) -> DocumentUploadJobResponse:
    """Derive a batch status directly from durable child workflow query results."""
    statuses = [str(state.get("status", "queued")) for state in child_states]
    if any(status == "failed" for status in statuses):
        status = "failed"
    elif statuses and all(status == "completed" for status in statuses):
        status = "completed"
    elif any(status == "processing" for status in statuses):
        status = "processing"
    else:
        status = "queued"
    documents = [
        document
        for state in child_states
        for document in state.get("documents", [])
        if isinstance(document, dict)
    ]
    errors = [str(state["error"]) for state in child_states if state.get("error")]
    return DocumentUploadJobResponse(
        job_id=job_id,
        status=status,
        progress=round(
            sum(int(state.get("progress", 0)) for state in child_states)
            / max(len(child_states), 1)
        ),
        stage="completed" if status == "completed" else "processing_batch",
        details={"workflow_ids": len(child_states), "statuses": statuses},
        documents=documents,
        error="; ".join(errors) if errors else None,
    )


def _process_saved_documents(
    saved_uploads: list[tuple[str, Path]],
    user: str,
    chat_id: str,
    progress_callback: UploadProgressCallback | None = None,
) -> list[UploadedDocumentResult]:
    """Preprocess, store, and attach saved PDFs while reporting completed work."""
    results: list[UploadedDocumentResult] = []
    total_files = len(saved_uploads)

    for file_index, (original_filename, saved_path) in enumerate(saved_uploads):

        def report_file_progress(
            percent: int,
            stage: str,
            details: dict[str, Any],
        ) -> None:
            if progress_callback is None:
                return
            overall = round((file_index * 100 + percent) / total_files)
            progress_callback(
                overall,
                stage,
                {
                    "filename": original_filename,
                    "file_number": file_index + 1,
                    "total_files": total_files,
                    **details,
                },
            )

        report_file_progress(1, "checking_existing_document", {})
        document_id = document_id_for_file(saved_path)
        existing_stats = document_ingestion_stats(document_id)
        if existing_stats is not None:
            saved_path.unlink(missing_ok=True)
            try:
                saved_path.parent.rmdir()
            except OSError:
                pass
            results.append(
                UploadedDocumentResult(
                    filename=original_filename,
                    document_id=document_id,
                    status="already_ingested",
                    **existing_stats,
                )
            )
            report_file_progress(98, "reusing_existing_document", existing_stats)
            logger.info(
                "Skipped preprocessing for an already ingested PDF",
                extra={
                    "filename": original_filename,
                    "document_id": document_id,
                    **existing_stats,
                },
            )
            continue

        logger.info(
            "Starting HTTP PDF ingestion", extra={"filename": original_filename}
        )
        try:
            bundle = process_document(
                str(saved_path),
                progress_callback=lambda percent, stage, details: report_file_progress(
                    round(percent * 0.7), stage, details
                ),
            )
            stats = ingest_bundle(
                bundle,
                progress_callback=lambda percent, stage, details: report_file_progress(
                    70 + round(percent * 0.28), stage, details
                ),
            )
        except Exception:
            logger.exception(
                "HTTP PDF ingestion failed", extra={"filename": original_filename}
            )
            raise
        results.append(
            UploadedDocumentResult(
                filename=original_filename,
                document_id=bundle["document"]["document_id"],
                status="ingested",
                **stats,
            )
        )
        report_file_progress(98, "document_stored", stats)
        logger.info(
            "Completed HTTP PDF ingestion",
            extra={
                "filename": original_filename,
                "document_id": bundle["document"]["document_id"],
                **stats,
            },
        )

    attach_documents_to_session(
        user, chat_id, [result.document_id for result in results]
    )
    if progress_callback is not None:
        progress_callback(
            100,
            "attached_to_chat",
            {"completed_files": total_files, "total_files": total_files},
        )
    return results


LOCAL_MODEL_ID = "morpheus-local"


async def _start_agent_workflow(
    latest_query: str,
    user_id: str,
    session_id: str,
    sanitized_messages: list[dict[str, Any]],
    model_name: str = "",
) -> tuple[Any, str]:
    """Start one durable agent workflow and return its handle and stable identifier."""
    workflow_id = _workflow_id(user_id, session_id)
    client = await Client.connect(TEMPORAL_ADDRESS)
    handle = await client.start_workflow(
        WORKFLOW_TYPE,
        args=[latest_query, user_id, session_id, sanitized_messages, model_name],
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    return handle, workflow_id


async def _workflow_state(workflow_id: str) -> WorkflowStateResponse:
    """Query the durable workflow state needed for UI progress and HITL prompts."""
    try:
        client = await Client.connect(TEMPORAL_ADDRESS)
        handle = client.get_workflow_handle(workflow_id)
        state = await handle.query("get_workflow_state")
    except Exception as error:
        logger.exception(
            "Temporal workflow state query failed", extra={"workflow_id": workflow_id}
        )
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "message": "Workflow was not found or is unavailable.",
                    "type": "not_found",
                }
            },
        ) from error

    return WorkflowStateResponse(
        workflow_id=workflow_id,
        status=str(state.get("status", "unknown")),
        user_choice=state.get("user_choice"),
        final_answer=str(state.get("final_answer", "")),
        execution_history=list(state.get("execution_history", [])),
    )


@app.post("/v1/documents/upload", response_model=DocumentUploadResponse)
async def upload_documents(
    files: list[UploadFile] = File(...),
    user: str = Form("usr_local"),
    chat_id: str = Form("sess_default"),
) -> DocumentUploadResponse:
    """Upload one or more PDFs, preprocess them, and atomically load pgvector tiers."""
    if not files:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "message": "At least one PDF file is required.",
                    "type": "invalid_file",
                }
            },
        )
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "message": f"A maximum of {MAX_UPLOAD_FILES} PDFs can be uploaded at once.",
                    "type": "too_many_files",
                }
            },
        )

    saved_uploads = [await _save_uploaded_pdf(upload) for upload in files]
    resolved_user = _resolve_user_id(user)
    try:
        results = await asyncio.to_thread(
            _process_saved_documents,
            saved_uploads,
            resolved_user,
            chat_id,
        )
    except Exception as error:
        logger.exception(
            "Synchronous document upload failed", extra={"chat_id": chat_id}
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": "Document ingestion failed.",
                    "type": "ingestion_failed",
                }
            },
        ) from error
    return DocumentUploadResponse(status="completed", documents=results)


@app.post(
    "/v1/documents/upload-jobs",
    status_code=202,
    response_model=DocumentUploadJobResponse,
)
async def start_document_upload_job(
    files: list[UploadFile] = File(...),
    user: str = Form("usr_local"),
    chat_id: str = Form("sess_default"),
) -> DocumentUploadJobResponse:
    """Persist PDFs quickly and process them in a pollable background job."""
    if not files:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "message": "At least one PDF file is required.",
                    "type": "invalid_file",
                }
            },
        )
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "message": f"A maximum of {MAX_UPLOAD_FILES} PDFs can be uploaded at once.",
                    "type": "too_many_files",
                }
            },
        )

    saved_uploads = [await _save_uploaded_pdf(upload) for upload in files]
    resolved_user = _resolve_user_id(user)
    workflow_ids: list[str] = []
    documents: list[dict[str, str]] = []
    try:
        client = await Client.connect(TEMPORAL_ADDRESS)
        for original_filename, saved_path in saved_uploads:
            document_id = document_id_for_file(saved_path)
            workflow_id = f"ingest-{document_id}"
            try:
                await client.start_workflow(
                    DocumentIngestionWorkflow.run,
                    args=[str(saved_path), resolved_user, chat_id],
                    id=workflow_id,
                    task_queue=TASK_QUEUE,
                )
            except WorkflowAlreadyStartedError:
                logger.info(
                    "Reusing in-flight document ingestion workflow",
                    extra={"workflow_id": workflow_id, "document_id": document_id},
                )
                await asyncio.to_thread(
                    attach_documents_to_session, resolved_user, chat_id, [document_id]
                )
            workflow_ids.append(workflow_id)
            documents.append(
                {"filename": original_filename, "document_id": document_id}
            )
    except Exception as error:
        logger.exception("Temporal ingestion workflow start failed")
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "message": "Document ingestion workflow is unavailable.",
                    "type": "service_unavailable",
                }
            },
        ) from error
    job_id = (
        workflow_ids[0] if len(workflow_ids) == 1 else _ingestion_batch_id(workflow_ids)
    )
    return DocumentUploadJobResponse(
        job_id=job_id,
        status="queued",
        progress=0,
        stage="queued",
        details={"documents": documents, "workflow_ids": workflow_ids},
    )


@app.get(
    "/v1/documents/upload-jobs/{job_id}",
    response_model=DocumentUploadJobResponse,
)
async def get_document_upload_job(job_id: str) -> DocumentUploadJobResponse:
    """Query the durable Temporal workflow state for one PDF upload job."""
    try:
        client = await Client.connect(TEMPORAL_ADDRESS)
        child_workflow_ids = _batch_workflow_ids(job_id) or [job_id]
        progress_states = await asyncio.gather(
            *[
                client.get_workflow_handle(workflow_id).query("get_ingestion_progress")
                for workflow_id in child_workflow_ids
            ]
        )
    except Exception as error:
        logger.exception(
            "Temporal ingestion progress query failed", extra={"job_id": job_id}
        )
        raise HTTPException(
            status_code=404,
            detail={
                "error": {"message": "Upload job was not found.", "type": "not_found"}
            },
        ) from error
    if len(progress_states) == 1:
        return DocumentUploadJobResponse(job_id=job_id, **progress_states[0])
    return _aggregate_ingestion_progress(job_id, list(progress_states))


@app.get("/v1/documents/{document_identifier:path}/view")
async def view_document(document_identifier: str) -> FileResponse:
    """Serve an uploaded PDF inline for direct in-browser page viewing."""
    identifier = unquote(document_identifier).strip().rstrip("]")
    try:
        path = get_document_source_path(identifier)
    except Exception as error:
        logger.exception(
            "Document view lookup failed", extra={"document_identifier": identifier}
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": "Document viewing failed.",
                    "type": "internal_error",
                }
            },
        ) from error
    if path is None or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "message": f"Document '{identifier}' was not found.",
                    "type": "not_found",
                }
            },
        )
    ascii_name = path.name.encode("ascii", "replace").decode("ascii").replace('"', "")
    return FileResponse(
        path=path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"inline; filename=\"{ascii_name}\"; "
                f"filename*=UTF-8''{quote(path.name)}"
            ),
            "X-Content-Type-Options": "nosniff",
            "Accept-Ranges": "bytes",
        },
    )


@app.get("/v1/documents/{doc_id}/figures/{figure_id}")
async def view_figure_image(doc_id: str, figure_id: str) -> Response:
    """Serve the stored binary figure image directly from PostgreSQL."""
    try:
        data = await asyncio.to_thread(get_figure_image_data, doc_id, figure_id)
    except Exception as error:
        logger.exception(
            "Figure image lookup failed", extra={"doc_id": doc_id, "figure_id": figure_id}
        )
        raise HTTPException(
            status_code=500,
            detail={"error": {"message": "Figure viewing failed.", "type": "internal_error"}},
        ) from error
    if data is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "message": f"Figure image '{figure_id}' was not found for document '{doc_id}'.",
                    "type": "not_found",
                }
            },
        )
    image_bytes, mime_type = data
    return Response(
        content=image_bytes,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{figure_id}.png"',
            "Cache-Control": "public, max-age=86400",
        },
    )


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    """Return the OpenAI-compatible models exposed by this service."""
    return {
        "object": "list",
        "data": [
            {"id": MODEL_ID, "object": "model", "owned_by": "morpheus-gemini"},
            {"id": LOCAL_MODEL_ID, "object": "model", "owned_by": "morpheus-local"},
        ],
    }


@app.post("/v1/chat/completions")
@traceable(name="openai_chat_completion", run_type="chain")
async def chat_completions(body: dict[str, Any]) -> dict[str, Any]:
    """Screen a chat turn and await its Temporal agent workflow response."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(
            status_code=422,
            detail={"error": {"message": "messages must be a list."}},
        )
    requested_model = str(body.get("model") or MODEL_ID)
    user_id = _resolve_user_id(body.get("user"))
    session_id = str(body.get("chat_id") or body.get("id", "sess_default"))
    latest_query, sanitized_messages = _sanitize_messages(messages)

    try:
        handle, workflow_id = await _start_agent_workflow(
            latest_query,
            user_id,
            session_id,
            sanitized_messages,
            model_name=requested_model,
        )
        result = await handle.result()
    except Exception as error:
        logger.exception(
            "Temporal workflow execution failed", extra={"workflow_id": workflow_id}
        )
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "message": "Agent workflow is unavailable.",
                    "type": "service_unavailable",
                }
            },
        ) from error

    final_answer = str(result.get("final_answer", ""))
    exposed_models = {MODEL_ID, LOCAL_MODEL_ID}
    response_model = requested_model if requested_model in exposed_models else MODEL_ID
    return {
        "id": f"chatcmpl-{session_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": response_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": final_answer},
                "finish_reason": "stop",
            }
        ],
    }


@app.post("/v1/chat/workflows", status_code=202, response_model=WorkflowStateResponse)
@traceable(name="openai_chat_workflow_start", run_type="chain")
async def start_chat_workflow(body: dict[str, Any]) -> WorkflowStateResponse:
    """Start a chat workflow without blocking a UI that must handle HITL events."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(
            status_code=422,
            detail={"error": {"message": "messages must be a list."}},
        )
    requested_model = str(body.get("model") or MODEL_ID)
    user_id = _resolve_user_id(body.get("user"))
    session_id = str(body.get("chat_id") or body.get("id", "sess_default"))
    latest_query, sanitized_messages = _sanitize_messages(messages)

    try:
        _, workflow_id = await _start_agent_workflow(
            latest_query,
            user_id,
            session_id,
            sanitized_messages,
            model_name=requested_model,
        )
    except Exception as error:
        logger.exception(
            "Temporal workflow start failed",
            extra={"user_id": user_id, "session_id": session_id},
        )
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "message": "Agent workflow is unavailable.",
                    "type": "service_unavailable",
                }
            },
        ) from error

    return WorkflowStateResponse(workflow_id=workflow_id, status="started")


@app.get("/v1/workflows/{workflow_id}", response_model=WorkflowStateResponse)
async def get_workflow_status(workflow_id: str) -> WorkflowStateResponse:
    """Return durable workflow progress for an Open WebUI polling integration."""
    return await _workflow_state(workflow_id)


@app.post(
    "/v1/workflows/{workflow_id}/clarification",
    status_code=202,
    response_model=WorkflowStateResponse,
)
async def submit_clarification(
    workflow_id: str, request: ClarificationSignalRequest
) -> WorkflowStateResponse:
    """Deliver one decision only while its Temporal workflow is awaiting clarification."""
    try:
        client = await Client.connect(TEMPORAL_ADDRESS)
        handle = client.get_workflow_handle(workflow_id)
        state = await handle.query("get_workflow_state")
    except RPCError as error:
        logger.exception(
            "Temporal clarification state query failed",
            extra={"workflow_id": workflow_id},
        )
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "message": "Workflow was not found or is unavailable.",
                    "type": "not_found",
                }
            },
        ) from error

    if state.get("status") != "awaiting_clarification":
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "message": "Workflow is not awaiting clarification.",
                    "type": "workflow_not_waiting",
                }
            },
        )

    try:
        await handle.signal("user_clarification_signal", request.choice)
    except RPCError as error:
        logger.exception(
            "Temporal clarification signal was rejected",
            extra={"workflow_id": workflow_id},
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "message": "Workflow no longer accepts clarification.",
                    "type": "workflow_not_waiting",
                }
            },
        ) from error

    return WorkflowStateResponse(
        workflow_id=workflow_id,
        status="awaiting_clarification",
        user_choice=request.choice,
        final_answer=str(state.get("final_answer", "")),
        execution_history=list(state.get("execution_history", [])),
    )
