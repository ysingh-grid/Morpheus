"""Deterministic Temporal orchestration for bounded LangGraph decisions."""

from __future__ import annotations

import asyncio
import re
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from agent.state import (
        append_tool_observation,
        compact_mcp_observation,
        compact_retrieval_observation,
        merge_retrieved_evidence,
    )
    from orchestration.mcp_client import default_web_search_tool

    from orchestration.activities import (
        attach_existing_document_activity,
        commit_document_bundle_activity,
        count_reindexable_children_activity,
        execute_tool_activity,
        extract_user_facts_activity,
        generate_embeddings_activity,
        fetch_unindexed_chunk_batch_activity,
        generate_direct_answer_activity,
        generate_answer_activity,
        get_full_table_activity,
        hash_and_deduplicate_document_activity,
        load_history_activity,
        parse_docling_layout_activity,
        persist_session_turn_activity,
        run_agent_graph_activity,
        run_agent_retrieval_activity,
        reindex_chunk_batch_activity,
        summarize_session_history_activity,
        verify_borderline_confidence_activity,
    )

MAX_AGENT_TURNS = 5
_PERSISTENT_MEMORY_REQUEST = re.compile(
    r"\b(?:remember|save|store|add)\b.{0,80}\b(?:about me|my (?:profile|information|details)|"
    r"persistent (?:memory|storage)|memory)\b|\b(?:persistent (?:memory|storage))\b",
    re.IGNORECASE,
)


def _explicit_memory_save_requested(query: str) -> bool:
    """Return whether the user explicitly asked to retain durable personal context."""
    return bool(_PERSISTENT_MEMORY_REQUEST.search(query))


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
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1), maximum_attempts=attempts
            ),
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
            "tool_observations": [],
            "completed_tools": [],
            "tool_errors": {},
            "needs_replan": False,
            "clarification_needed": False,
            "context_sufficient": False,
            "user_choice": "",
            "final_answer": "",
            "iteration_count": 0,
            "max_turns": MAX_AGENT_TURNS,
            "verification_pending": False,
        }
        memory_save_requested = _explicit_memory_save_requested(query)
        self.status = "loading_history"
        try:
            session_context = await self._activity(
                load_history_activity, [user_id, session_id], 15, 2
            )
            state["history"] = session_context.get("messages", [])
            state["conversation_summary"] = session_context.get(
                "conversation_summary", ""
            )
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
                await self._act_retrieval(state, query)
                continue
            if action == "mcp_search":
                if await self._act_mcp(state, session_id):
                    break
                continue
            if action == "generate_answer":
                await self._act_answer(state, query, memory_save_requested)
                break
            if action == "direct_answer":
                await self._act_direct_answer(state, query, memory_save_requested)
                break
            if action == "ask_clarification":
                if await self._act_clarification(state):
                    break
                continue

        else:
            state["final_answer"] = (
                "I could not complete this request safely. Please clarify it."
            )
            self._publish_terminal_state(state, "turn_limit_reached")
            self.execution_history.append("agent_turn_limit_reached")

        if memory_save_requested:
            try:
                facts_persisted = await self._activity(
                    extract_user_facts_activity,
                    [user_id, query, state.get("final_answer", "")],
                    30,
                    3,
                )
            except ActivityError:
                self.execution_history.append("user_fact_persistence_failed")
                state["final_answer"] = (
                    f"{state.get('final_answer', '')}\n\n"
                    "I could not save the requested information to persistent memory."
                ).strip()
            else:
                if facts_persisted:
                    self.execution_history.append("user_facts_persisted_on_request")
                    state["final_answer"] = (
                        f"{state.get('final_answer', '')}\n\n"
                        "I saved the relevant profile information to persistent memory."
                    ).strip()
                else:
                    self.execution_history.append("no_user_facts_to_persist_on_request")
                    state["final_answer"] = (
                        f"{state.get('final_answer', '')}\n\n"
                        "I could not identify durable personal information to save from this exchange."
                    ).strip()
        else:
            self._start_fact_extraction(user_id, query, state.get("final_answer", ""))
        if memory_save_requested and self.status == "generating_answer":
            self._publish_terminal_state(state, "completed")
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
        self.execution_history.append("workflow_completed")
        self.final_answer = state.get("final_answer", "")
        return self._response(state)

    def _pending_mcp_tool(self, state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Return the next unfinished MCP/native tool and its planned arguments."""
        plan = dict(state.get("agent_plan") or {})
        completed_tools = set(state.get("completed_tools") or [])
        tool_name = next(
            (
                name
                for name in plan.get("tool_sequence", [])
                if name != "hybrid_search" and name not in completed_tools
            ),
            "",
        )
        arguments = dict(plan.get("tool_arguments", {}).get(tool_name, {}))
        web_search_tool = default_web_search_tool()
        if tool_name == web_search_tool and not arguments:
            arguments = {"query": str(plan.get("web_query") or state.get("query") or "")}
        return tool_name, arguments

    def _is_web_search_tool(self, tool_name: str) -> bool:
        """Gate only Tavily; calculator, fetch, and table tools stay ungated."""
        web_search_tool = default_web_search_tool()
        return bool(web_search_tool) and tool_name == web_search_tool

    def _mark_observed(self, state: dict[str, Any], observation: dict[str, Any]) -> None:
        """Record one tool observation and force the next think step to re-plan."""
        state["tool_observations"] = append_tool_observation(
            state.get("tool_observations"), observation
        )
        state["needs_replan"] = True

    async def _await_web_search_approval(self, state: dict[str, Any]) -> str:
        """Pause for Tavily HITL. Returns approve_web_search, cancel, or timeout."""
        existing = str(state.get("user_choice") or "")
        if existing in {"approve_web_search", "cancel"}:
            return existing
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
            return "timeout"
        if self.user_choice != "approve_web_search":
            state["user_choice"] = "cancel"
            return "cancel"
        state["user_choice"] = "approve_web_search"
        state["clarification_needed"] = False
        self.execution_history.append("clarification_approved_web_search")
        return "approve_web_search"

    def _reject_web_search(self, state: dict[str, Any], tool_name: str) -> None:
        """Keep thinking after a declined web search; never run Tavily on this turn."""
        web_search_tool = default_web_search_tool() or tool_name
        state["user_choice"] = "cancel"
        state["clarification_needed"] = False
        if web_search_tool and web_search_tool not in state.get("completed_tools", []):
            state["completed_tools"] = [
                *state.get("completed_tools", []),
                web_search_tool,
            ]
        state["tool_errors"][web_search_tool] = "Web search was declined by the user."
        self._mark_observed(
            state,
            compact_mcp_observation(
                tool_name=web_search_tool,
                arguments={},
                error="Web search was declined by the user.",
            ),
        )
        self.status = "reasoning"
        self.execution_history.append("clarification_cancelled")

    def _enable_approved_web_search(self, state: dict[str, Any]) -> None:
        """Keep Tavily on the plan after HITL so the next think/act can dispatch it."""
        web_search_tool = default_web_search_tool()
        state["completed_tools"] = [
            tool
            for tool in state.get("completed_tools", [])
            if tool != web_search_tool
        ]
        plan = dict(state.get("agent_plan") or {})
        planned_tools = list(plan.get("tool_sequence", []))
        if web_search_tool and web_search_tool not in planned_tools:
            planned_tools.append(web_search_tool)
        plan["tool_sequence"] = planned_tools
        if plan.get("intent") == "clarify":
            plan["intent"] = "web"
        state["agent_plan"] = plan
        state["needs_replan"] = False

    async def _act_retrieval(self, state: dict[str, Any], query: str) -> None:
        """Run hybrid search, optional borderline verify, then observe."""
        self.execution_history.append("pgvector_retrieval_started")
        document_query = str(
            state.get("agent_plan", {}).get("document_query") or query
        )
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
            state["tool_errors"]["hybrid_search"] = (
                "Document retrieval was unavailable."
            )
            state["completed_tools"].append("hybrid_search")
            self._mark_observed(
                state,
                compact_retrieval_observation(
                    document_query=document_query,
                    document_lookup=document_lookup,
                    retrieval={},
                    error="Document retrieval was unavailable.",
                ),
            )
            return
        state["retrieval_response"] = retrieval
        state["retrieved_evidence"] = merge_retrieved_evidence(
            state.get("retrieved_evidence"), retrieval["evidence"]
        )
        state["completed_tools"].append("hybrid_search")
        document_only = bool(state.get("agent_plan", {}).get("document_only"))
        force_document_check = document_only and (
            retrieval["status"] != "grounded"
            or not retrieval.get("confidence", {}).get("lexical_match", False)
        )
        verification_evidence = merge_retrieved_evidence(
            retrieval["evidence"], state.get("retrieved_evidence")
        )
        context_sufficient: bool | None = None
        if retrieval["status"] == "clarification_needed" or force_document_check:
            try:
                verified_sufficient = await self._activity(
                    verify_borderline_confidence_activity,
                    [
                        query,
                        retrieval,
                        verification_evidence,
                        force_document_check,
                    ],
                    30,
                    2,
                )
                state["context_sufficient"] = verified_sufficient or bool(
                    state.get("context_sufficient")
                )
            except ActivityError:
                state["context_sufficient"] = False
                self.execution_history.append("borderline_verification_failed")
            context_sufficient = bool(state["context_sufficient"])
            state["verification_pending"] = True
        self._mark_observed(
            state,
            compact_retrieval_observation(
                document_query=document_query,
                document_lookup=document_lookup,
                retrieval=retrieval,
                context_sufficient=context_sufficient,
            ),
        )

    async def _act_mcp(self, state: dict[str, Any], session_id: str) -> bool:
        """Run one MCP/native tool. Tavily always waits for HITL. True means stop."""
        tool_name, arguments = self._pending_mcp_tool(state)
        if not tool_name:
            state["tool_errors"]["mcp"] = "No registered MCP tool was selected."
            state["needs_replan"] = True
            return False
        if (
            self._is_web_search_tool(tool_name)
            and state.get("user_choice") != "approve_web_search"
        ):
            decision = await self._await_web_search_approval(state)
            if decision == "timeout":
                return True
            if decision == "cancel":
                self._reject_web_search(state, tool_name)
                return False
            self._enable_approved_web_search(state)
        self.status = "web_searching"
        self.execution_history.append(f"mcp_tool_started:{tool_name}")
        try:
            if tool_name == "get_full_table":
                result_reference = await self._activity(
                    get_full_table_activity,
                    [
                        session_id,
                        str(arguments.get("doc_id", "")),
                        str(arguments.get("table_id", "")),
                        state.get("document_ids", []),
                    ],
                    30,
                    2,
                )
            else:
                result_reference = await self._activity(
                    execute_tool_activity,
                    [session_id, tool_name, arguments],
                    45,
                    3,
                )
        except ActivityError:
            self.execution_history.append(f"mcp_tool_failed:{tool_name}")
            state["tool_errors"][tool_name] = (
                f"The selected tool '{tool_name}' was unavailable."
            )
            state["completed_tools"].append(tool_name)
            self._mark_observed(
                state,
                compact_mcp_observation(
                    tool_name=tool_name,
                    arguments=arguments,
                    error=f"The selected tool '{tool_name}' was unavailable.",
                ),
            )
            return False
        state["mcp_results"] = [*state["mcp_results"], result_reference]
        state["completed_tools"].append(tool_name)
        state["clarification_needed"] = False
        self._mark_observed(
            state,
            compact_mcp_observation(
                tool_name=tool_name,
                arguments=arguments,
                result=result_reference,
            ),
        )
        return False

    async def _act_answer(
        self, state: dict[str, Any], query: str, memory_save_requested: bool
    ) -> None:
        """Generate a grounded answer from accumulated evidence."""
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
            return
        if not memory_save_requested:
            self._publish_terminal_state(state, "completed")
        self.execution_history.append("answer_generated")

    async def _act_direct_answer(
        self, state: dict[str, Any], query: str, memory_save_requested: bool
    ) -> None:
        """Generate a tool-free conversational answer."""
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
            return
        if not memory_save_requested:
            self._publish_terminal_state(state, "completed")
        self.execution_history.append("answer_generated")

    async def _act_clarification(self, state: dict[str, Any]) -> bool:
        """Document-only misses stay terminal; otherwise pause for Tavily approval."""
        plan = state.get("agent_plan", {})
        if plan.get("document_only") and state.get("clarification_needed"):
            self._publish_terminal_state(state, "not_found")
            self.execution_history.append("retrieval_not_found")
            return True
        decision = await self._await_web_search_approval(state)
        if decision == "timeout":
            return True
        if decision == "cancel":
            self._reject_web_search(state, default_web_search_tool() or "tavily_search")
            return False
        self._enable_approved_web_search(state)
        self.status = "reasoning"
        return False

    def _start_fact_extraction(self, user_id: str, query: str, answer: str) -> None:
        """Persist explicit user facts without delaying the answer response."""
        workflow.start_activity(
            extract_user_facts_activity,
            args=[user_id, query, answer],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1), maximum_attempts=3
            ),
            cancellation_type=workflow.ActivityCancellationType.ABANDON,
        )
        self.execution_history.append("user_fact_extraction_started")

    def _response(self, state: dict[str, Any]) -> dict[str, Any]:
        """Return compact references so Temporal never transports raw source payloads."""
        sources_used: list[str] = []
        if state.get("retrieval_response"):
            sources_used.append("pgvector")
        if state.get("mcp_results"):
            mcp_tool_names = {
                str(reference.get("tool_name", ""))
                for reference in state["mcp_results"]
            }
            sources_used.append(
                "mcp_web_search"
                if mcp_tool_names == {default_web_search_tool()}
                else "mcp_tools"
            )
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
                timedelta(seconds=heartbeat_seconds)
                if heartbeat_seconds is not None
                else None
            ),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1), maximum_attempts=attempts
            ),
        )

    @workflow.run
    async def run(
        self, file_path: str, user_id: str, session_id: str
    ) -> dict[str, Any]:
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


@workflow.defn
class BatchReindexWorkflow:
    """Durably rebuild child embeddings in independent, retry-safe batches."""

    def __init__(self) -> None:
        """Initialize compact, queryable reindex progress state."""
        self.status = "queued"
        self.processed_count = 0
        self.total_count = 0
        self.last_processed_id: str | None = None
        self.error: str | None = None

    @workflow.query
    def get_reindex_status(self) -> dict[str, Any]:
        """Expose durable batch progress without returning child text or vectors."""
        return {
            "status": self.status,
            "processed_count": self.processed_count,
            "total_count": self.total_count,
            "last_processed_id": self.last_processed_id,
            "error": self.error,
        }

    async def _activity(
        self,
        activity_function: Any,
        args: list[Any],
        timeout_seconds: int,
        attempts: int,
    ) -> Any:
        """Run one idempotent reindex activity with exponential Temporal retries."""
        return await workflow.execute_activity(
            activity_function,
            args=args,
            start_to_close_timeout=timedelta(seconds=timeout_seconds),
            heartbeat_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=attempts,
            ),
        )

    @workflow.run
    async def run(self, batch_size: int = 100) -> dict[str, Any]:
        """Process all children after the current cursor without workflow payload bloat."""
        if batch_size < 1 or batch_size > 1_000:
            self.status = "failed"
            self.error = "batch_size must be between 1 and 1000."
            return self.get_reindex_status()
        self.status = "counting"
        try:
            self.total_count = int(
                await self._activity(count_reindexable_children_activity, [], 30, 3)
            )
            self.status = "reindexing"
            while True:
                chunks = await self._activity(
                    fetch_unindexed_chunk_batch_activity,
                    [batch_size, self.last_processed_id],
                    30,
                    3,
                )
                if not chunks:
                    break
                last_processed_id = str(
                    await self._activity(reindex_chunk_batch_activity, [chunks], 300, 5)
                )
                expected_last_id = str(chunks[-1]["id"])
                if last_processed_id != expected_last_id:
                    raise RuntimeError(
                        "Reindex activity returned an unexpected cursor ID."
                    )
                self.last_processed_id = last_processed_id
                self.processed_count += len(chunks)
        except (ActivityError, RuntimeError):
            self.status = "failed"
            self.error = "Batch reindexing failed. Check the Morpheus service logs."
            return self.get_reindex_status()

        self.status = "completed"
        return self.get_reindex_status()
