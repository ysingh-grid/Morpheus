"""Start a durable Temporal workflow that rebuilds every child embedding."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from temporalio.client import Client

from orchestration.worker import TASK_QUEUE
from orchestration.workflows import BatchReindexWorkflow

logger = logging.getLogger(__name__)


async def trigger_reindex(batch_size: int, workflow_id: str | None = None) -> str:
    """Start one batch reindex workflow and return its durable execution ID."""
    if batch_size < 1 or batch_size > 1_000:
        raise ValueError("batch_size must be between 1 and 1000.")
    client = await Client.connect(os.getenv("TEMPORAL_ADDRESS", "localhost:7233"))
    execution_id = workflow_id or f"batch-reindex-{uuid4()}"
    handle = await client.start_workflow(
        BatchReindexWorkflow.run,
        args=[batch_size],
        id=execution_id,
        task_queue=TASK_QUEUE,
    )
    logger.info(
        "Started batch reindex workflow",
        extra={"workflow_id": handle.id, "batch_size": batch_size},
    )
    return handle.id


def main() -> None:
    """Parse CLI options and launch the durable batch reindex workflow."""
    parser = argparse.ArgumentParser(description="Start a durable pgvector batch reindex.")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--workflow-id", default=None)
    arguments = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    workflow_id = asyncio.run(trigger_reindex(arguments.batch_size, arguments.workflow_id))
    print(f"Started batch reindex workflow: {workflow_id}")


if __name__ == "__main__":
    main()
