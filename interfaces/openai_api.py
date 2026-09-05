"""OpenAI-compatible HTTP gateway for the durable RAG agent workflow."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from temporalio.client import Client

from ingestion.doc_processor import document_id_for_file, process_document
from retrieval.pg_engine import (
    attach_documents_to_session,
    document_ingestion_stats,
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

app = FastAPI(title="Morpheus OpenAI-Compatible API", version="0.1.0")
UploadProgressCallback = Callable[[int, str, dict[str, Any]], None]
_UPLOAD_JOBS: dict[str, dict[str, Any]] = {}
_UPLOAD_JOBS_LOCK = threading.Lock()
# OcrMac uses Apple Vision/MPS resources that are not safe for concurrent Docling jobs.
_UPLOAD_PROCESSING_LOCK = threading.Lock()


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


def _sanitize_messages(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Run the security boundary on every user turn before Temporal receives it."""
    if not messages:
        raise HTTPException(
            status_code=422,
            detail={"error": {"message": "At least one chat message is required."}},
        )

    sanitized_messages: list[dict[str, Any]] = []
    latest_sanitized_query = ""
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise HTTPException(
                status_code=422,
                detail={"error": {"message": "Each message must be an object."}},
            )
        sanitized_message = dict(message)
        content = _message_content(sanitized_message)
        scan_result = guardrails.scan_user_input(content)
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
        if index == len(messages) - 1:
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


def _update_upload_job(job_id: str, **updates: Any) -> None:
    """Apply one thread-safe, monotonic update to an in-process upload job."""
    with _UPLOAD_JOBS_LOCK:
        job = _UPLOAD_JOBS[job_id]
        if "progress" in updates:
            updates["progress"] = max(int(job["progress"]), int(updates["progress"]))
        job.update(updates)


def _upload_job_snapshot(job_id: str) -> DocumentUploadJobResponse:
    """Return a validated copy of one upload job or a stable 404 response."""
    with _UPLOAD_JOBS_LOCK:
        job = _UPLOAD_JOBS.get(job_id)
        snapshot = dict(job) if job is not None else None
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {"message": "Upload job was not found.", "type": "not_found"}
            },
        )
    return DocumentUploadJobResponse.model_validate(snapshot)


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


def _run_upload_job(
    job_id: str,
    saved_uploads: list[tuple[str, Path]],
    user: str,
    chat_id: str,
) -> None:
    """Execute a background upload job and retain its latest pollable state."""
    _update_upload_job(
        job_id,
        status="processing",
        stage="waiting_for_document_processor",
        progress=0,
    )

    def update_progress(percent: int, stage: str, details: dict[str, Any]) -> None:
        _update_upload_job(job_id, progress=percent, stage=stage, details=details)

    logger.info(
        "Upload job waiting for exclusive document processor", extra={"job_id": job_id}
    )
    with _UPLOAD_PROCESSING_LOCK:
        _update_upload_job(job_id, stage="starting", progress=0)
        logger.info(
            "Upload job acquired exclusive document processor", extra={"job_id": job_id}
        )
        try:
            results = _process_saved_documents(
                saved_uploads,
                user,
                chat_id,
                progress_callback=update_progress,
            )
        except Exception:
            _update_upload_job(
                job_id,
                status="failed",
                stage="failed",
                error="Document processing failed. Check the Morpheus service logs.",
            )
            return
    _update_upload_job(
        job_id,
        status="completed",
        progress=100,
        stage="completed",
        documents=[result.model_dump(mode="json") for result in results],
    )


async def _start_agent_workflow(
    latest_query: str,
    user_id: str,
    session_id: str,
    sanitized_messages: list[dict[str, Any]],
) -> tuple[Any, str]:
    """Start one durable agent workflow and return its handle and stable identifier."""
    workflow_id = _workflow_id(user_id, session_id)
    client = await Client.connect(TEMPORAL_ADDRESS)
    handle = await client.start_workflow(
        WORKFLOW_TYPE,
        args=[latest_query, user_id, session_id, sanitized_messages],
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
    try:
        results = await asyncio.to_thread(
            _process_saved_documents,
            saved_uploads,
            user,
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
    background_tasks: BackgroundTasks,
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
    job_id = f"upload-{uuid4()}"
    with _UPLOAD_JOBS_LOCK:
        _UPLOAD_JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0,
            "stage": "queued",
            "details": {"total_files": len(saved_uploads)},
            "documents": [],
            "error": None,
        }
    background_tasks.add_task(_run_upload_job, job_id, saved_uploads, user, chat_id)
    return _upload_job_snapshot(job_id)


@app.get(
    "/v1/documents/upload-jobs/{job_id}",
    response_model=DocumentUploadJobResponse,
)
async def get_document_upload_job(job_id: str) -> DocumentUploadJobResponse:
    """Return the latest completed-work percentage for one PDF upload job."""
    return _upload_job_snapshot(job_id)


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    """Return the single OpenAI-compatible model exposed by this service."""
    return {
        "object": "list",
        "data": [{"id": MODEL_ID, "object": "model", "owned_by": MODEL_ID}],
    }


@app.post("/v1/chat/completions")
async def chat_completions(body: dict[str, Any]) -> dict[str, Any]:
    """Screen a chat turn and await its Temporal agent workflow response."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(
            status_code=422,
            detail={"error": {"message": "messages must be a list."}},
        )
    _requested_model = body.get("model", MODEL_ID)
    del _requested_model
    user_id = str(body.get("user", "usr_local"))
    session_id = str(body.get("chat_id") or body.get("id", "sess_default"))
    latest_query, sanitized_messages = _sanitize_messages(messages)

    try:
        handle, workflow_id = await _start_agent_workflow(
            latest_query, user_id, session_id, sanitized_messages
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
    return {
        "id": f"chatcmpl-{session_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": final_answer},
                "finish_reason": "stop",
            }
        ],
    }


@app.post("/v1/chat/workflows", status_code=202, response_model=WorkflowStateResponse)
async def start_chat_workflow(body: dict[str, Any]) -> WorkflowStateResponse:
    """Start a chat workflow without blocking a UI that must handle HITL events."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(
            status_code=422,
            detail={"error": {"message": "messages must be a list."}},
        )
    user_id = str(body.get("user", "usr_local"))
    session_id = str(body.get("chat_id") or body.get("id", "sess_default"))
    latest_query, sanitized_messages = _sanitize_messages(messages)

    try:
        _, workflow_id = await _start_agent_workflow(
            latest_query, user_id, session_id, sanitized_messages
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
    """Deliver one validated human approval or cancellation signal to Temporal."""
    try:
        client = await Client.connect(TEMPORAL_ADDRESS)
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal("user_clarification_signal", request.choice)
    except Exception as error:
        logger.exception(
            "Temporal clarification signal failed", extra={"workflow_id": workflow_id}
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

    return await _workflow_state(workflow_id)
