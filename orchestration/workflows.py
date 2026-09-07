"""Deterministic Temporal orchestration for bounded LangGraph decisions."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from orchestration.activities import (
        attach_existing_document_activity,
        commit_document_bundle_activity,
        execute_agent_mcp_activity,
        extract_user_facts_activity,
        generate_embeddings_activity,
        generate_direct_answer_activity,
        generate_answer_activity,
        hash_and_deduplicate_document_activity,
        load_history_activity,
        parse_docling_layout_activity,
        persist_session_turn_activity,
        run_agent_graph_activity,
        run_agent_retrieval_activity,
        summarize_session_history_activity,
        verify_borderline_confidence_activity,
    )

MAX_AGENT_TURNS = 5


@workflow.defn
class AgentWorkflow:
    """Run one tool per activity so retries never replay prior side effects."""

    def __init__(self) -> None:
        """Initialize durable, replay-safe workflow state."""
        self.user_choice: str | None = None
        self.status = "created"
        self.final_answer = ""
        self.execution_history: list[str] = []

    @workflow.signal
    def user_clarification_signal(self, choice: str) -> None:
        """Persist only the first valid clarification decision for this workflow."""
        if self.user_choice is not None:
            self.execution_history.append("clarification:ignored_after_decision")
            return
        if choice == "approve_web_search":
            self.user_choice = choice
            self.execution_history.append("clarification:approve_web_search")
            return
        self.user_choice = "cancel"
        self.execution_history.append("clarification:cancel")

    @workflow.query
    def get_workflow_state(self) -> dict[str, Any]:
        """Expose durable HITL and bounded-turn state to a client."""
        return {
            "status": self.status,
            "user_choice": self.user_choice,
            "final_answer": self.final_answer,
            "execution_history": self.execution_history,
        }

    def _publish_terminal_state(self, state: dict[str, Any], status: str) -> None:
        """Publish the answer before exposing a terminal workflow status."""
        self.final_answer = str(state.get("final_answer", ""))
        self.status = status

    async def _activity(
        self,
        activity_function: Any,
        args: list[Any],
        timeout_seconds: int,
        attempts: int,
    ) -> Any:
        """Execute exactly one side-effecting operation with its own retry scope."""
        return await workflow.execute_activity(
            activity_function,
            args=args,
            start_to_close_timeout=timedelta(seconds=timeout_seconds),
            retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=attempts),
        )

    @workflow.run
    async def run(
        self,
        query: str,
        user_id: str,
        session_id: str | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Execute bounded decisions, isolated tools, and durable HITL resumption."""
        session_id = session_id or workflow.info().workflow_id
        state: dict[str, Any] = {
            "query": query,
            "user_id": user_id,
            "session_id": session_id,
            "messages": messages or [{"role": "user", "content": query}],
            "document_ids": [],
            "attached_documents": [],
            "retrieved_evidence": [],
            "mcp_results": [],
            "completed_tools": [],
            "tool_errors": {},
            "clarification_needed": False,
            "context_sufficient": False,
            "user_choice": "",
            "final_answer": "",
            "iteration_count": 0,
            "max_turns": MAX_AGENT_TURNS,
            "verification_pending": False,
        }
        self.status = "loading_history"
        try:
            session_context = await self._activity(load_history_activity, [user_id, session_id], 15, 2)
            state["history"] = session_context.get("messages", [])
            state["conversation_summary"] = session_context.get("conversation_summary", "")
            state["document_ids"] = session_context.get("document_ids", [])
            state["attached_documents"] = session_context.get("attached_documents", [])
        except ActivityError:
            self.status = "history_load_failed"
            self.execution_history.append("history_load_failed")
            return self._response(state)

        while state["iteration_count"] < MAX_AGENT_TURNS:
            state["iteration_count"] += 1
            self.status = "reasoning"
            self.execution_history.append(f"agent_turn:{state['iteration_count']}")
            try:
                state = await self._activity(run_agent_graph_activity, [state], 10, 1)
            except ActivityError:
                self.status = "agent_decision_failed"
                self.execution_history.append("agent_decision_failed")
                break

            action = state["next_action"]
            if action == "hybrid_search":
                self.execution_history.append("pgvector_retrieval_started")
                document_query = str(state.get("agent_plan", {}).get("document_query") or query)
                document_lookup = str(
                    state.get("agent_plan", {}).get("document_lookup") or "semantic"
                )
                try:
                    retrieval = await self._activity(
                        run_agent_retrieval_activity,
                        [document_query, 5, state["document_ids"], document_lookup],
                        30,
                        2,
                    )
                except ActivityError:
                    self.execution_history.append("pgvector_retrieval_failed")
                    state["tool_errors"]["hybrid_search"] = "Document retrieval was unavailable."
                    state["completed_tools"].append("hybrid_search")
                    continue
                state["retrieval_response"] = retrieval
                state["retrieved_evidence"] = retrieval["evidence"]
                state["completed_tools"].append("hybrid_search")
                document_only = bool(state.get("agent_plan", {}).get("document_only"))
                force_document_check = document_only and (
                    retrieval["status"] != "grounded"
                    or not retrieval.get("confidence", {}).get("lexical_match", False)
                )
                if retrieval["status"] == "clarification_needed" or force_document_check:
                    try:
                        state["context_sufficient"] = await self._activity(
                            verify_borderline_confidence_activity,
                            [
                                query,
                                retrieval,
                                state["retrieved_evidence"],
                                force_document_check,
                            ],
                            30,
                            2,
                        )
                    except ActivityError:
                        state["context_sufficient"] = False
                        self.execution_history.append("borderline_verification_failed")
                    state["verification_pending"] = True
                continue

            if action == "mcp_search":
                self.status = "web_searching"
                self.execution_history.append("mcp_web_search_started")
                web_query = str(state.get("agent_plan", {}).get("web_query") or query)
                try:
                    result_reference = await self._activity(
                        execute_agent_mcp_activity,
                        [session_id, web_query],
                        45,
                        3,
                    )
                except ActivityError:
                    self.execution_history.append("mcp_web_search_failed")
                    state["tool_errors"]["mcp_search"] = "Web search was unavailable."
                    state["completed_tools"].append("mcp_search")
                    continue
                state["mcp_results"] = [*state["mcp_results"], result_reference]
                state["completed_tools"].append("mcp_search")
                state["clarification_needed"] = False
                continue

            if action == "generate_answer":
                self.status = "generating_answer"
                try:
                    state["final_answer"] = await self._activity(
                        generate_answer_activity,
                        [
                            query,
                            state["retrieved_evidence"],
                            state["mcp_results"],
                            state["messages"],
                        ],
                        45,
                        2,
                    )
                except ActivityError:
                    self.status = "answer_generation_failed"
                    self.execution_history.append("answer_generation_failed")
                else:
                    self._publish_terminal_state(state, "completed")
                    self.execution_history.append("answer_generated")
                break

            if action == "direct_answer":
                self.status = "generating_answer"
                self.execution_history.append("direct_answer_started")
                try:
                    state["final_answer"] = await self._activity(
                        generate_direct_answer_activity,
                        [query, state["messages"], state["tool_errors"]],
                        45,
                        2,
                    )
                except ActivityError:
                    self.status = "answer_generation_failed"
                    self.execution_history.append("answer_generation_failed")
                else:
                    self._publish_terminal_state(state, "completed")
                    self.execution_history.append("answer_generated")
                break

            if action == "ask_clarification":
                plan = state.get("agent_plan", {})
                if plan.get("document_only") and state.get("clarification_needed"):
                    self._publish_terminal_state(state, "not_found")
                    self.execution_history.append("retrieval_not_found")
                    break

                self.status = "awaiting_clarification"
                self.execution_history.append("workflow_paused_for_clarification")
                try:
                    await workflow.wait_condition(
                        lambda: self.user_choice is not None,
                        timeout=timedelta(hours=24),
                        timeout_summary="clarification_expiry",
                    )
                except asyncio.TimeoutError:
                    state["final_answer"] = "Clarification/search was not approved."
                    self._publish_terminal_state(state, "timed_out")
                    self.execution_history.append("clarification_timed_out")
                    break

                if self.user_choice != "approve_web_search":
                    state["final_answer"] = "Clarification/search was not approved."
                    self._publish_terminal_state(state, "cancelled")
                    self.execution_history.append("clarification_cancelled")
                    break

                state["user_choice"] = self.user_choice
                state["clarification_needed"] = False
                state["completed_tools"] = [
                    tool for tool in state["completed_tools"] if tool != "mcp_search"
                ]
                plan = dict(state.get("agent_plan", {}))
                planned_tools = list(plan.get("tool_sequence", []))
                if "mcp_search" not in planned_tools:
                    planned_tools.append("mcp_search")
                plan["tool_sequence"] = planned_tools
                if plan.get("intent") == "clarify":
                    plan["intent"] = "web_search"
                state["agent_plan"] = plan
                self.status = "reasoning"
                self.execution_history.append("clarification_approved_web_search")
                continue

        else:
            state["final_answer"] = "I could not complete this request safely. Please clarify it."
            self._publish_terminal_state(state, "turn_limit_reached")
            self.execution_history.append("agent_turn_limit_reached")

        try:
            await self._activity(
                persist_session_turn_activity,
                [user_id, session_id, state["messages"], state.get("final_answer", "")],
                15,
                2,
            )
        except ActivityError:
            self.execution_history.append("session_persistence_failed")
        else:
            self.execution_history.append("session_persisted")
        if len(state["messages"]) >= 6:
            workflow.start_activity(
                summarize_session_history_activity,
                args=[user_id, session_id, state["messages"]],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1), maximum_attempts=2
                ),
                cancellation_type=workflow.ActivityCancellationType.ABANDON,
            )
            self.execution_history.append("session_history_summarization_started")
        self._start_fact_extraction(user_id, query, state.get("final_answer", ""))
        self.execution_history.append("workflow_completed")
        self.final_answer = state.get("final_answer", "")
        return self._response(state)

    def _start_fact_extraction(self, user_id: str, query: str, answer: str) -> None:
        """Persist explicit user facts without delaying the answer response."""
        workflow.start_activity(
            extract_user_facts_activity,
            args=[user_id, query, answer],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=3),
            cancellation_type=workflow.ActivityCancellationType.ABANDON,
        )
        self.execution_history.append("user_fact_extraction_started")

    def _response(self, state: dict[str, Any]) -> dict[str, Any]:
        """Return compact references so Temporal never transports raw source payloads."""
        sources_used: list[str] = []
        if state.get("retrieval_response"):
            sources_used.append("pgvector")
        if state.get("mcp_results"):
            sources_used.append("mcp_web_search")
        if not sources_used:
            sources_used.append("agent")
        evidence = (
            []
            if self.status == "not_found"
            else [*state.get("retrieved_evidence", []), *state.get("mcp_results", [])]
        )
        return {
            "status": self.status,
            "retrieval": state.get("retrieval_response", {}),
            "evidence": evidence,
            "final_answer": state.get("final_answer", ""),
            "sources_used": sources_used,
            "execution_history": self.execution_history,
        }


@workflow.defn
class DocumentIngestionWorkflow:
    """Durably parse, embed, store, and attach one uploaded document."""

    def __init__(self) -> None:
        """Initialize queryable ingestion progress without process-local state."""
        self.status = "queued"
        self.stage = "queued"
        self.progress = 0
        self.details: dict[str, Any] = {}
        self.documents: list[dict[str, Any]] = []
        self.error: str | None = None

    @workflow.query
    def get_ingestion_progress(self) -> dict[str, Any]:
        """Expose durable ingestion state for gateway and UI polling."""
        return {
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "details": self.details,
            "documents": self.documents,
            "error": self.error,
        }

    def _set_progress(
        self, *, stage: str, progress: int, details: dict[str, Any] | None = None
    ) -> None:
        """Apply one monotonic, replay-safe workflow progress update."""
        self.stage = stage
        self.progress = max(self.progress, min(progress, 100))
        if details is not None:
            self.details = details

    async def _activity(
        self,
        activity_function: Any,
        args: list[Any],
        timeout_seconds: int,
        attempts: int,
        heartbeat_seconds: int | None = None,
    ) -> Any:
        """Run one ingestion side effect with bounded retries and heartbeats."""
        return await workflow.execute_activity(
            activity_function,
            args=args,
            start_to_close_timeout=timedelta(seconds=timeout_seconds),
            heartbeat_timeout=(
                timedelta(seconds=heartbeat_seconds) if heartbeat_seconds is not None else None
            ),
            retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=attempts),
        )

    @workflow.run
    async def run(self, file_path: str, user_id: str, session_id: str) -> dict[str, Any]:
        """Execute the four durable ingestion stages for one saved upload."""
        self.status = "processing"
        try:
            self._set_progress(stage="checking_existing_document", progress=5)
            deduplication = await self._activity(
                hash_and_deduplicate_document_activity, [file_path], 60, 3, 30
            )
            document_id = str(deduplication["document_id"])
            if deduplication["already_ingested"]:
                self._set_progress(stage="attaching_existing_document", progress=90)
                await self._activity(
                    attach_existing_document_activity,
                    [document_id, user_id, session_id],
                    30,
                    3,
                )
                self.documents = [
                    {
                        "filename": str(deduplication["filename"]),
                        "document_id": document_id,
                        "status": "already_ingested",
                        **dict(deduplication["stats"]),
                    }
                ]
                self.status = "completed"
                self._set_progress(stage="completed", progress=100)
                return self.get_ingestion_progress()

            self._set_progress(stage="parsing_document_layout", progress=10)
            parsed_document = await self._activity(
                parse_docling_layout_activity, [file_path], 1_800, 3, 120
            )
            self._set_progress(
                stage="generating_embeddings",
                progress=65,
                details={"children": int(parsed_document["children"])},
            )
            generated_embeddings = await self._activity(
                generate_embeddings_activity,
                [str(parsed_document["bundle_reference"])],
                600,
                5,
                60,
            )
            self._set_progress(stage="committing_document_bundle", progress=90)
            document = await self._activity(
                commit_document_bundle_activity,
                [
                    str(parsed_document["bundle_reference"]),
                    str(generated_embeddings["embeddings_reference"]),
                    user_id,
                    session_id,
                ],
                180,
                3,
                60,
            )
        except ActivityError:
            self.status = "failed"
            self.error = "Document processing failed. Check the Morpheus service logs."
            self._set_progress(stage="failed", progress=self.progress)
            return self.get_ingestion_progress()

        self.documents = [dict(document)]
        self.status = "completed"
        self._set_progress(stage="completed", progress=100)
        return self.get_ingestion_progress()
