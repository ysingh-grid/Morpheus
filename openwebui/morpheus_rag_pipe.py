"""
title: Morpheus RAG Agent
author: Morpheus
version: 1.0.0
required_open_webui_version: 0.10.0
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field


EventCall = Callable[[dict[str, Any]], Awaitable[Any]]
EventEmitter = Callable[[dict[str, Any]], Awaitable[Any]]


class Pipe:
    """Expose the durable Morpheus RAG workflow as an Open WebUI chat model."""

    class Valves(BaseModel):
        """Administrator-configurable gateway connection and polling limits."""

        MORPHEUS_API_BASE_URL: str = Field(
            default="http://host.docker.internal:8000/v1",
            description="Morpheus gateway URL reachable from the Open WebUI container.",
        )
        DOCUMENT_VIEW_BASE_URL: str = Field(
            default="http://localhost:8000/v1",
            description="Morpheus gateway URL reachable from the user's browser for PDF viewing.",
        )
        REQUEST_TIMEOUT_SECONDS: int = Field(default=1800, ge=1, le=3600)
        POLL_INTERVAL_SECONDS: float = Field(default=1.0, ge=0.1, le=30.0)
        MAX_STATUS_POLLS: int = Field(default=1800, ge=1, le=3600)

    def __init__(self) -> None:
        """Initialize Pipe settings with safe Docker Desktop defaults."""
        self.valves = self.Valves()
        self._uploaded_attachments_by_chat: dict[str, set[str]] = {}

    def pipes(self) -> list[dict[str, str]]:
        """Register this Pipe as a selectable model in Open WebUI."""
        return [{"id": "morpheus-rag-agent", "name": "Morpheus RAG Agent"}]

    @staticmethod
    def _content_to_text(content: Any) -> str:
        """Normalize Open WebUI/OpenAI message content to plain text for the gateway."""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts = [
                str(part.get("text", "")).strip()
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            return "\n".join(part for part in text_parts if part)
        return ""

    @staticmethod
    def _local_utility_response(
        task: str | None,
        prompt: str,
        task_body: dict[str, Any] | None,
    ) -> str | None:
        """Handle Open WebUI metadata tasks without starting a Morpheus workflow."""
        normalized_task = (task or "").strip().lower()
        normalized_prompt = prompt.strip().lower()
        if not normalized_task and not (
            normalized_prompt.startswith("### task:")
            and "### guidelines:" in normalized_prompt
            and "### output:" in normalized_prompt
            and "### chat history:" in normalized_prompt
        ):
            return None

        if normalized_task == "title_generation" or (
            not normalized_task
            and "generate a concise title summarizing the chat history"
            in normalized_prompt
        ):
            source_messages = (
                task_body.get("messages", []) if isinstance(task_body, dict) else []
            )
            first_user_text = next(
                (
                    Pipe._content_to_text(message.get("content"))
                    for message in source_messages
                    if isinstance(message, dict) and message.get("role") == "user"
                ),
                "Morpheus Chat",
            )
            words = re.findall(r"[A-Za-z0-9]+", first_user_text)
            title = " ".join(words[:4]).strip() or "Morpheus Chat"
            return json.dumps({"title": title})
        if normalized_task == "follow_up_generation" or (
            not normalized_task
            and "suggest 3-5 relevant follow-up questions or prompts"
            in normalized_prompt
        ):
            return json.dumps({"follow_ups": []})
        if normalized_task == "tags_generation" or (
            not normalized_task
            and "generate 1-3 broad tags categorizing the main themes"
            in normalized_prompt
        ):
            return json.dumps({"tags": ["General"]})
        if normalized_task == "query_generation" or (
            not normalized_task
            and "analyze the chat history to determine the necessity of generating search queries"
            in normalized_prompt
        ):
            return json.dumps({"queries": []})
        if normalized_task == "emoji_generation":
            return json.dumps({"emoji": ""})
        if normalized_task in {"image_prompt_generation", "autocomplete_generation"}:
            return ""
        return None

    @staticmethod
    def _unwrap_openwebui_context_prompt(prompt: str) -> str:
        """Recover the original question from Open WebUI's built-in RAG wrapper."""
        normalized = prompt.strip().lower()
        marker = "</context>"
        if not (
            normalized.startswith("### task:")
            and "respond to the user query using the provided context" in normalized
            and marker in normalized
        ):
            return prompt
        marker_index = normalized.rfind(marker)
        original_query = prompt[marker_index + len(marker) :].strip()
        return original_query or prompt

    @staticmethod
    def _attached_pdf_paths(files: list[dict[str, Any]] | None) -> list[Path]:
        """Return readable PDF attachments from Open WebUI's reserved files argument."""
        pdf_paths: list[Path] = []
        for entry in files or []:
            file_data = entry.get("file", entry) if isinstance(entry, dict) else {}
            path_value = file_data.get("path") if isinstance(file_data, dict) else None
            if not isinstance(path_value, str):
                continue
            path = Path(path_value)
            if path.suffix.lower() == ".pdf" and path.is_file():
                pdf_paths.append(path)
        return pdf_paths

    @staticmethod
    def _attachment_key(path: Path) -> str:
        """Identify one Open WebUI attachment without reading its full contents."""
        stat = path.stat()
        return f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"

    async def _emit_status(
        self, emitter: EventEmitter | None, description: str, done: bool = False
    ) -> None:
        """Show one native Open WebUI workflow-progress status event."""
        if emitter is None:
            return
        await emitter(
            {
                "type": "status",
                "data": {"description": description, "done": done, "hidden": False},
            }
        )

    def _url(self, path: str) -> str:
        """Build one gateway URL without permitting arbitrary redirect targets."""
        return f"{self.valves.MORPHEUS_API_BASE_URL.rstrip('/')}{path}"

    @staticmethod
    def _remove_automatic_source_markers(answer: str) -> str:
        """Remove legacy Open WebUI numeric markers from a Morpheus-owned answer."""
        return re.sub(r"\s*\[\d+\](?=\s*(?:\[Source:|$|[.,;:]))", "", answer)

    def _format_source_bubbles(self, answer: str) -> str:
        """Transform text citations like [Source: doc.pdf, p. 1] into clean clickable markdown links."""
        pattern = re.compile(
            r"\[Source:\s*(?P<document>.+?),\s*pp?\.\s*(?P<pages>[0-9,\s\-–]+)\]",
            re.IGNORECASE,
        )

        def replace_citation(match: re.Match[str]) -> str:
            raw_document = match.group("document").strip()
            pages = match.group("pages").strip()
            first_page_match = re.search(r"\d+", pages)
            first_page = first_page_match.group(0) if first_page_match else "1"
            clean_name = re.sub(
                r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}_", "", raw_document
            )
            display_name = clean_name
            if len(display_name) > 30:
                stem = Path(clean_name).stem
                suffix = Path(clean_name).suffix
                display_name = f"{stem[:22]}…{suffix}" if len(stem) > 22 else clean_name
            view_base = self.valves.DOCUMENT_VIEW_BASE_URL.rstrip("/")
            encoded_doc = quote(raw_document)
            view_url = f"{view_base}/documents/{encoded_doc}/view#page={first_page}"
            return f" [📄 {display_name} · p. {pages}]({view_url})"

        return pattern.sub(replace_citation, answer)

    async def _emit_sources(
        self, emitter: EventEmitter | None, answer: str
    ) -> None:
        """Emit native Open WebUI source metadata cards for cited documents."""
        if emitter is None:
            return
        pattern = re.compile(
            r"\[Source:\s*(?P<document>.+?),\s*pp?\.\s*(?P<pages>[0-9,\s\-–]+)\]",
            re.IGNORECASE,
        )
        seen: set[str] = set()
        for match in pattern.finditer(answer):
            raw_document = match.group("document").strip()
            pages = match.group("pages").strip()
            key = f"{raw_document}:{pages}"
            if key in seen:
                continue
            seen.add(key)
            first_page_match = re.search(r"\d+", pages)
            first_page = first_page_match.group(0) if first_page_match else "1"
            clean_name = re.sub(
                r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}_", "", raw_document
            )
            view_base = self.valves.DOCUMENT_VIEW_BASE_URL.rstrip("/")
            encoded_doc = quote(raw_document)
            view_url = f"{view_base}/documents/{encoded_doc}/view#page={first_page}"
            title = f"{clean_name} (p. {pages})"
            await emitter(
                {
                    "type": "source",
                    "data": {
                        "source": {"name": title, "url": view_url},
                        "document": [f"Cited passage from {clean_name}, page {pages}."],
                        "metadata": [{"source": view_url, "name": title}],
                    },
                }
            )

    @staticmethod
    def _http_json(
        method: str,
        url: str,
        body: bytes | None,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        """Perform one bounded HTTP request and decode its JSON response."""
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                payload = response.read().decode("utf-8")
        except HTTPError as error:
            response_text = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Morpheus gateway returned HTTP {error.code}: {response_text}"
            ) from error
        except URLError as error:
            raise RuntimeError(
                "Morpheus gateway is unreachable from Open WebUI."
            ) from error
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                "Morpheus gateway returned an invalid JSON response."
            ) from error
        if not isinstance(decoded, dict):
            raise RuntimeError("Morpheus gateway returned an unexpected JSON response.")
        return decoded

    async def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute a JSON gateway request off the Open WebUI event loop."""
        request_headers = {"Accept": "application/json", **(headers or {})}
        request_body = body
        if payload is not None:
            request_body = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        return await asyncio.to_thread(
            self._http_json,
            method,
            self._url(path),
            request_body,
            request_headers,
            self.valves.REQUEST_TIMEOUT_SECONDS,
        )

    async def _upload_pdfs(
        self,
        pdf_paths: list[Path],
        user_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Submit PDFs and their owning chat identity as one multipart request."""
        boundary = f"----morpheus-{uuid.uuid4().hex}"
        body_parts: list[bytes] = []
        for field_name, field_value in (("user", user_id), ("chat_id", session_id)):
            safe_value = field_value.replace("\r", "").replace("\n", "")
            body_parts.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{field_name}"\r\n\r\n'.encode(),
                    safe_value.encode(),
                    b"\r\n",
                ]
            )
        for pdf_path in pdf_paths:
            content_type = mimetypes.guess_type(pdf_path.name)[0] or "application/pdf"
            body_parts.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    (
                        "Content-Disposition: form-data; "
                        f' name="files"; filename="{pdf_path.name}"\r\n'
                    ).encode(),
                    f"Content-Type: {content_type}\r\n\r\n".encode(),
                    pdf_path.read_bytes(),
                    b"\r\n",
                ]
            )
        body_parts.append(f"--{boundary}--\r\n".encode())
        return await self._request_json(
            "POST",
            "/documents/upload-jobs",
            body=b"".join(body_parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    @staticmethod
    def _upload_progress_text(state: dict[str, Any]) -> str:
        """Render one compact, factual ingestion status for Open WebUI."""
        progress = int(state.get("progress", 0))
        stage = str(state.get("stage", "processing")).replace("_", " ")
        details = state.get("details") if isinstance(state.get("details"), dict) else {}
        filename = str(details.get("filename", "document"))
        completed = details.get("completed")
        total = details.get("total")
        counter = (
            f" ({completed}/{total})"
            if completed is not None and total is not None
            else ""
        )
        return f"{filename}: {progress}% — {stage}{counter}"

    async def _wait_for_upload_job(
        self,
        initial_state: dict[str, Any],
        emitter: EventEmitter | None,
    ) -> dict[str, Any]:
        """Poll one background ingestion job while emitting visible progress."""
        job_id = initial_state.get("job_id")
        if not job_id and isinstance(initial_state.get("documents"), list):
            return initial_state
        if not isinstance(job_id, str) or not job_id:
            raise RuntimeError("Morpheus did not return an upload job identifier.")
        state = initial_state
        last_progress: tuple[int, str] | None = None
        for _ in range(self.valves.MAX_STATUS_POLLS):
            status = str(state.get("status", "unknown"))
            progress_key = (int(state.get("progress", 0)), str(state.get("stage", "")))
            if progress_key != last_progress:
                await self._emit_status(emitter, self._upload_progress_text(state))
                last_progress = progress_key
            if status == "completed":
                return state
            if status == "failed":
                raise RuntimeError(
                    str(state.get("error") or "Document processing failed.")
                )
            await asyncio.sleep(self.valves.POLL_INTERVAL_SECONDS)
            state = await self._request_json("GET", f"/documents/upload-jobs/{job_id}")
        raise RuntimeError("Document processing timed out before completion.")

    @staticmethod
    def _confirmation_approved(result: Any) -> bool:
        """Interpret Open WebUI confirmation results and fail closed on disconnects."""
        if isinstance(result, dict):
            if result.get("error"):
                return False
            return bool(
                result.get("confirmed", result.get("ok", result.get("result", False)))
            )
        return result is True

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any] | None = None,
        __metadata__: dict[str, Any] | None = None,
        __chat_id__: str | None = None,
        __session_id__: str | None = None,
        __task__: str | None = None,
        __task_body__: dict[str, Any] | None = None,
        __event_emitter__: EventEmitter | None = None,
        __event_call__: EventCall | None = None,
        __files__: list[dict[str, Any]] | None = None,
    ) -> str:
        """Upload PDFs, run a durable workflow, and handle in-chat web-search approval."""
        messages = [
            {
                "role": str(message.get("role", "user")),
                "content": self._content_to_text(message.get("content")),
            }
            for message in body.get("messages", [])
            if isinstance(message, dict)
            and self._content_to_text(message.get("content"))
        ]
        if not messages or messages[-1]["role"] != "user":
            return "Please send a text question to Morpheus."

        utility_response = self._local_utility_response(
            __task__, messages[-1]["content"], __task_body__
        )
        if utility_response is not None:
            return utility_response
        messages[-1]["content"] = self._unwrap_openwebui_context_prompt(
            messages[-1]["content"]
        )

        user_id = str((__user__ or {}).get("id", "usr_openwebui"))
        body_metadata = (
            body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
        )
        metadata = __metadata__ if isinstance(__metadata__, dict) else body_metadata
        session_id = str(
            __chat_id__
            or metadata.get("chat_id")
            or body.get("chat_id")
            or __session_id__
            or metadata.get("session_id")
            or uuid.uuid4()
        )
        pdf_paths = self._attached_pdf_paths(__files__)
        if __files__ and not pdf_paths:
            return "Morpheus currently accepts PDF chat attachments only."
        uploaded_keys = self._uploaded_attachments_by_chat.setdefault(session_id, set())
        new_pdf_paths = [
            path
            for path in pdf_paths
            if self._attachment_key(path) not in uploaded_keys
        ]
        if new_pdf_paths:
            await self._emit_status(
                __event_emitter__,
                f"Uploading and preprocessing {len(new_pdf_paths)} new PDF document(s)…",
            )
            try:
                upload_job = await self._upload_pdfs(new_pdf_paths, user_id, session_id)
                upload_result = await self._wait_for_upload_job(
                    upload_job, __event_emitter__
                )
            except RuntimeError as error:
                return f"Document upload failed: {error}"
            uploaded_keys.update(self._attachment_key(path) for path in new_pdf_paths)
            count = len(upload_result.get("documents", []))
            await self._emit_status(
                __event_emitter__, f"Loaded {count} PDF document(s) into Morpheus."
            )

        await self._emit_status(
            __event_emitter__, "Morpheus is deciding how to respond…"
        )
        try:
            workflow = await self._request_json(
                "POST",
                "/chat/workflows",
                {"user": user_id, "chat_id": session_id, "messages": messages},
            )
        except RuntimeError as error:
            return f"Morpheus workflow could not start: {error}"
        workflow_id = workflow.get("workflow_id")
        if not isinstance(workflow_id, str) or not workflow_id:
            return "Morpheus did not return a workflow identifier."

        emitted_history: set[str] = set()
        empty_completed_polls = 0
        for _ in range(self.valves.MAX_STATUS_POLLS):
            try:
                state = await self._request_json("GET", f"/workflows/{workflow_id}")
            except RuntimeError as error:
                return f"Morpheus workflow status failed: {error}"
            status = str(state.get("status", "unknown"))
            history = {
                str(entry)
                for entry in state.get("execution_history", [])
                if isinstance(entry, str)
            }
            if (
                "pgvector_retrieval_started" in history
                and "pgvector_retrieval_started" not in emitted_history
            ):
                await self._emit_status(
                    __event_emitter__, "Searching documents attached to this chat…"
                )
            if (
                "mcp_web_search_started" in history
                and "mcp_web_search_started" not in emitted_history
            ):
                await self._emit_status(
                    __event_emitter__, "Searching the web with Tavily…"
                )
            if (
                "direct_answer_started" in history
                and "direct_answer_started" not in emitted_history
            ):
                await self._emit_status(
                    __event_emitter__, "Responding conversationally…"
                )
            emitted_history.update(history)
            if status == "awaiting_clarification":
                if __event_call__ is None:
                    choice = "cancel"
                else:
                    confirmation = await __event_call__(
                        {
                            "type": "confirmation",
                            "data": {
                                "title": "Allow web search?",
                                "message": (
                                    "The uploaded documents are insufficient or ambiguous. "
                                    "May Morpheus search the web with Tavily?"
                                ),
                            },
                        }
                    )
                    choice = (
                        "approve_web_search"
                        if self._confirmation_approved(confirmation)
                        else "cancel"
                    )
                await self._emit_status(
                    __event_emitter__, "Sending your web-search decision…"
                )
                try:
                    await self._request_json(
                        "POST",
                        f"/workflows/{workflow_id}/clarification",
                        {"choice": choice},
                    )
                except RuntimeError as error:
                    return f"Morpheus could not apply your decision: {error}"
            elif status == "completed":
                answer = str(state.get("final_answer", "")).strip()
                if not answer:
                    empty_completed_polls += 1
                    if empty_completed_polls < 5:
                        await self._emit_status(
                            __event_emitter__, "Finalizing the answer…"
                        )
                        await asyncio.sleep(self.valves.POLL_INTERVAL_SECONDS)
                        continue
                    await self._emit_status(
                        __event_emitter__,
                        "Morpheus completed without publishing an answer.",
                        done=True,
                    )
                    return "Morpheus completed without a final answer."
                await self._emit_sources(__event_emitter__, answer)
                await self._emit_status(
                    __event_emitter__, "Morpheus workflow completed.", done=True
                )
                return self._format_source_bubbles(
                    self._remove_automatic_source_markers(answer)
                )
            elif status in {
                "not_found",
                "cancelled",
                "turn_limit_reached",
                "retrieval_failed",
                "answer_generation_failed",
            }:
                answer = str(state.get("final_answer", "")).strip()
                await self._emit_status(
                    __event_emitter__, f"Morpheus workflow ended: {status}.", done=True
                )
                formatted = self._format_source_bubbles(
                    self._remove_automatic_source_markers(answer)
                )
                return formatted or f"Morpheus workflow ended with status: {status}."
            else:
                await self._emit_status(
                    __event_emitter__, f"Morpheus workflow status: {status}."
                )
            await asyncio.sleep(self.valves.POLL_INTERVAL_SECONDS)
        return "Morpheus workflow timed out while waiting for a final answer."
