"""Temporal worker entry point for the RAG agent task queue."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from orchestration.activities import (
    attach_existing_document_activity,
    commit_document_bundle_activity,
    count_reindexable_children_activity,
    execute_tool_activity,
    extract_user_facts_activity,
    fetch_unindexed_chunk_batch_activity,
    generate_embeddings_activity,
    generate_direct_answer_activity,
    generate_answer_activity,
    get_full_table_activity,
    hash_and_deduplicate_document_activity,
    ingest_document_activity,
    load_history_activity,
    parse_docling_layout_activity,
    persist_session_turn_activity,
    run_agent_graph_activity,
    run_agent_retrieval_activity,
    run_pgvector_retrieval_activity,
    reindex_chunk_batch_activity,
    summarize_session_history_activity,
    verify_borderline_confidence_activity,
)
from orchestration.workflows import AgentWorkflow, BatchReindexWorkflow, DocumentIngestionWorkflow

logger = logging.getLogger(__name__)

TASK_QUEUE = "rag-agent-queue"


async def run_worker() -> None:
    """Connect a worker to Temporal and wait for SIGINT or SIGTERM."""
    client = await Client.connect(os.getenv("TEMPORAL_ADDRESS", "localhost:7233"))
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(shutdown_signal, shutdown_event.set)

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="rag-activity") as activity_executor:
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[AgentWorkflow, DocumentIngestionWorkflow, BatchReindexWorkflow],
            activities=[
                ingest_document_activity,
                hash_and_deduplicate_document_activity,
                parse_docling_layout_activity,
                generate_embeddings_activity,
                commit_document_bundle_activity,
                count_reindexable_children_activity,
                attach_existing_document_activity,
                fetch_unindexed_chunk_batch_activity,
                run_pgvector_retrieval_activity,
                reindex_chunk_batch_activity,
                run_agent_graph_activity,
                execute_tool_activity,
                get_full_table_activity,
                load_history_activity,
                persist_session_turn_activity,
                summarize_session_history_activity,
                run_agent_retrieval_activity,
                verify_borderline_confidence_activity,
                generate_direct_answer_activity,
                generate_answer_activity,
                extract_user_facts_activity,
            ],
            activity_executor=activity_executor,
        )
        logger.info("Temporal RAG worker started", extra={"task_queue": TASK_QUEUE})
        worker_task = asyncio.create_task(worker.run())
        await shutdown_event.wait()
        logger.info("Temporal RAG worker shutting down")
        await worker.shutdown()
        await worker_task


def main() -> None:
    """Run the Temporal worker as a Python module entry point."""
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
