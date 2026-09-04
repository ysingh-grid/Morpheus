"""Uvicorn entry point for the OpenAI-compatible gateway."""

from __future__ import annotations

import asyncio
import logging

import uvicorn


logger = logging.getLogger(__name__)


async def run_server() -> None:
    """Start the reloadable local gateway server."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting OpenAI-compatible API gateway on http://0.0.0.0:8000")
    uvicorn.run("interfaces.openai_api:app", host="0.0.0.0", port=8000, reload=True)


def main() -> None:
    """Run the gateway entry point as a Python module."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
