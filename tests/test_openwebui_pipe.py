"""Unit coverage for the native Open WebUI Morpheus Pipe."""

from __future__ import annotations

import asyncio
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


def test_pipe_uploads_pdf_then_returns_completed_workflow_answer(tmp_path: Path) -> None:
    """A PDF attachment follows the gateway upload and completed-workflow path."""
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 test")
    pipe = Pipe()
    pipe.valves.POLL_INTERVAL_SECONDS = 0.1
    pipe._upload_pdfs = AsyncMock(return_value={"documents": [{"document_id": "doc-1"}]})
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

    result = asyncio.run(pipe.pipe(_body("What was the amount?"), __event_call__=event_call))

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


def test_pipe_rejects_non_pdf_attachments_without_calling_gateway(tmp_path: Path) -> None:
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


def test_pipe_does_not_reupload_same_attachment_on_later_chat_turn(tmp_path: Path) -> None:
    """A reserved stable chat ID preserves document scope across later turns."""
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 test")
    pipe = Pipe()
    pipe.valves.POLL_INTERVAL_SECONDS = 0.1
    pipe._upload_pdfs = AsyncMock(return_value={"documents": [{"document_id": "doc-1"}]})
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
        pipe.pipe(body_without_metadata("First question"), __chat_id__="stable-chat", __files__=files)
    )
    second = asyncio.run(
        pipe.pipe(body_without_metadata("Second question"), __chat_id__="stable-chat", __files__=files)
    )

    assert first == "First answer."
    assert second == "Second answer."
    pipe._upload_pdfs.assert_awaited_once_with([pdf_path], "usr_openwebui", "stable-chat")
    workflow_requests = [
        call.args
        for call in pipe._request_json.await_args_list
        if call.args[:2] == ("POST", "/chat/workflows")
    ]
    assert all(call[2]["chat_id"] == "stable-chat" for call in workflow_requests)
