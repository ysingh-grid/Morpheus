"""Unit coverage for the native Open WebUI Morpheus Pipe."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from openwebui.morpheus_rag_pipe import Pipe


def _body(question: str) -> dict[str, Any]:
    """Build a minimal Open WebUI Pipe input payload."""
    return {
        "metadata": {"chat_id": "chat-123"},
        "messages": [{"role": "user", "content": question}],
    }


def test_pipe_uploads_pdf_then_returns_completed_workflow_answer(
    tmp_path: Path,
) -> None:
    """A PDF attachment follows the gateway upload and completed-workflow path."""
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 test")
    pipe = Pipe()
    pipe.valves.POLL_INTERVAL_SECONDS = 0.1
    pipe._upload_pdfs = AsyncMock(
        return_value={"documents": [{"document_id": "doc-1"}]}
    )
    pipe._request_json = AsyncMock(
        side_effect=[
            {"workflow_id": "wf-1", "status": "started"},
            {"status": "completed", "final_answer": "Grounded answer."},
        ]
    )
    emitter = AsyncMock()

    result = asyncio.run(
        pipe.pipe(
            _body("What does the report say?"),
            __user__={"id": "user-1"},
            __files__=[{"file": {"path": str(pdf_path)}}],
            __event_emitter__=emitter,
        )
    )

    assert result == "Grounded answer."
    pipe._upload_pdfs.assert_awaited_once_with([pdf_path], "user-1", "chat-123")
    assert pipe._request_json.await_args_list[0].args == (
        "POST",
        "/chat/workflows",
        {
            "user": "user-1",
            "chat_id": "chat-123",
            "messages": [{"role": "user", "content": "What does the report say?"}],
        },
    )
    assert emitter.await_count >= 3


def test_pipe_requests_confirmation_then_signals_approved_web_search() -> None:
    """An ambiguous workflow uses the native Open WebUI confirmation dialog."""
    pipe = Pipe()
    pipe.valves.POLL_INTERVAL_SECONDS = 0.1
    pipe._request_json = AsyncMock(
        side_effect=[
            {"workflow_id": "wf-2", "status": "started"},
            {"status": "awaiting_clarification", "final_answer": ""},
            {"status": "reasoning"},
            {"status": "completed", "final_answer": "Web-assisted answer."},
        ]
    )
    event_call = AsyncMock(return_value=True)

    result = asyncio.run(
        pipe.pipe(_body("What was the amount?"), __event_call__=event_call)
    )

    assert result == "Web-assisted answer."
    event_call.assert_awaited_once()
    assert pipe._request_json.await_args_list[2].args == (
        "POST",
        "/workflows/wf-2/clarification",
        {"choice": "approve_web_search"},
    )


def test_pipe_waits_when_completed_status_precedes_final_answer() -> None:
    """A transient empty terminal query must not become the user-visible answer."""
    pipe = Pipe()
    pipe.valves.POLL_INTERVAL_SECONDS = 0.1
    pipe._request_json = AsyncMock(
        side_effect=[
            {"workflow_id": "wf-race", "status": "started"},
            {"status": "completed", "final_answer": ""},
            {"status": "completed", "final_answer": "Document title."},
        ]
    )

    result = asyncio.run(pipe.pipe(_body("What is the title?")))

    assert result == "Document title."
    assert pipe._request_json.await_count == 3


def test_pipe_emits_background_document_processing_progress(tmp_path: Path) -> None:
    """Large-document job stages are visible before the chat workflow starts."""
    pdf_path = tmp_path / "large-report.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 test")
    pipe = Pipe()
    pipe.valves.POLL_INTERVAL_SECONDS = 0.1
    pipe._upload_pdfs = AsyncMock(
        return_value={
            "job_id": "upload-1",
            "status": "queued",
            "progress": 0,
            "stage": "queued",
        }
    )
    pipe._request_json = AsyncMock(
        side_effect=[
            {
                "job_id": "upload-1",
                "status": "processing",
                "progress": 40,
                "stage": "captioning_figures",
                "details": {"filename": "large-report.pdf", "completed": 2, "total": 5},
            },
            {
                "job_id": "upload-1",
                "status": "completed",
                "progress": 100,
                "stage": "completed",
                "details": {"filename": "large-report.pdf"},
                "documents": [{"document_id": "document-1"}],
            },
            {"workflow_id": "wf-progress", "status": "started"},
            {"status": "completed", "final_answer": "Processed answer."},
        ]
    )
    emitter = AsyncMock()

    result = asyncio.run(
        pipe.pipe(
            _body("Summarize the report."),
            __files__=[{"file": {"path": str(pdf_path)}}],
            __event_emitter__=emitter,
        )
    )

    descriptions = [
        call.args[0]["data"]["description"] for call in emitter.await_args_list
    ]
    assert result == "Processed answer."
    assert any(
        "40%" in description and "captioning figures (2/5)" in description
        for description in descriptions
    )
    assert any("100%" in description for description in descriptions)


def test_pipe_rejects_non_pdf_attachments_without_calling_gateway(
    tmp_path: Path,
) -> None:
    """Unsupported attachments never reach the Morpheus upload endpoint."""
    text_path = tmp_path / "notes.txt"
    text_path.write_text("not a PDF", encoding="utf-8")
    pipe = Pipe()
    pipe._request_json = AsyncMock()

    result = asyncio.run(
        pipe.pipe(_body("Read this."), __files__=[{"file": {"path": str(text_path)}}])
    )

    assert result == "Morpheus currently accepts PDF chat attachments only."
    pipe._request_json.assert_not_awaited()


def test_pipe_does_not_reupload_same_attachment_on_later_chat_turn(
    tmp_path: Path,
) -> None:
    """A reserved stable chat ID preserves document scope across later turns."""
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 test")
    pipe = Pipe()
    pipe.valves.POLL_INTERVAL_SECONDS = 0.1
    pipe._upload_pdfs = AsyncMock(
        return_value={"documents": [{"document_id": "doc-1"}]}
    )
    pipe._request_json = AsyncMock(
        side_effect=[
            {"workflow_id": "wf-1"},
            {"status": "completed", "final_answer": "First answer."},
            {"workflow_id": "wf-2"},
            {"status": "completed", "final_answer": "Second answer."},
        ]
    )
    files = [{"file": {"path": str(pdf_path)}}]

    body_without_metadata = lambda question: {  # noqa: E731
        "messages": [{"role": "user", "content": question}]
    }
    first = asyncio.run(
        pipe.pipe(
            body_without_metadata("First question"),
            __chat_id__="stable-chat",
            __files__=files,
        )
    )
    second = asyncio.run(
        pipe.pipe(
            body_without_metadata("Second question"),
            __chat_id__="stable-chat",
            __files__=files,
        )
    )

    assert first == "First answer."
    assert second == "Second answer."
    pipe._upload_pdfs.assert_awaited_once_with(
        [pdf_path], "usr_openwebui", "stable-chat"
    )
    workflow_requests = [
        call.args
        for call in pipe._request_json.await_args_list
        if call.args[:2] == ("POST", "/chat/workflows")
    ]
    assert all(call[2]["chat_id"] == "stable-chat" for call in workflow_requests)


def test_pipe_removes_automatic_numeric_source_markers() -> None:
    """Morpheus owns visible source citations and never returns Open WebUI's [1] markers."""
    answer = "The deadline is August 10 [1] [Source: circular.pdf, p. 1]."

    assert Pipe._remove_automatic_source_markers(answer) == (
        "The deadline is August 10 [Source: circular.pdf, p. 1]."
    )


def test_pipe_formats_source_citations_as_clickable_bubbles() -> None:
    """Citations are transformed into subtle, grey clickable markdown links opening PDF pages."""
    pipe = Pipe()
    answer = "Passed with 981 [Source: AWS Certified Cloud Practitioner.pdf, p. 1]."
    formatted = pipe._format_source_bubbles(answer)

    assert "text-gray-400" in formatted
    assert "color: #9ca3af" in formatted
    assert "📄 AWS Certified….pdf · p. 1" in formatted
    assert "(http://localhost:8000/v1/documents/AWS%20Certified%20Cloud%20Practitioner.pdf/view#page=1)" in formatted


def test_pipe_handles_openwebui_utility_task_without_calling_gateway() -> None:
    """Open WebUI title generation stays outside the agent and its session memory."""
    pipe = Pipe()
    pipe._request_json = AsyncMock()

    result = asyncio.run(
        pipe.pipe(
            _body("### Task:\nGenerate a concise title summarizing the chat history."),
            __task__="title_generation",
            __task_body__={
                "messages": [{"role": "user", "content": "Explain IFC governance"}]
            },
        )
    )

    assert json.loads(result) == {"title": "Explain IFC governance"}
    pipe._request_json.assert_not_awaited()


def test_pipe_unwraps_openwebui_document_context_before_agent_execution() -> None:
    """Open WebUI's own extracted context never becomes the agent retrieval query."""
    pipe = Pipe()
    pipe.valves.POLL_INTERVAL_SECONDS = 0.1
    pipe._request_json = AsyncMock(
        side_effect=[
            {"workflow_id": "wf-context"},
            {"status": "completed", "final_answer": "IFC answer."},
        ]
    )
    wrapped = (
        "### Task:\nRespond to the user query using the provided context.\n"
        "<context><source id=\"1\">large extracted document</source></context>\n\n"
        "What is this document about?"
    )

    result = asyncio.run(pipe.pipe(_body(wrapped)))

    assert result == "IFC answer."
    assert pipe._request_json.await_args_list[0].args[2]["messages"][-1]["content"] == (
        "What is this document about?"
    )
