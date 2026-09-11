---
type: "query"
date: "2026-09-06T14:31:40.659760+00:00"
question: "What is Morpheus still missing relative to agentic RAG over personal documents?"
contributor: "graphify"
source_nodes: ["Pipe,documents,children,agent_progress_missing,orchestration_progress_missing,retrieval_progress_missing,ingestion_progress_missing,_sanitize_messages()"]
---

# Q: What is Morpheus still missing relative to agentic RAG over personal documents?

## Answer

The core path exists: PDF ingestion, normalized parent-child-table-figure storage, pgvector hybrid retrieval, LangGraph planning, Temporal execution, Tavily approval, citations, and Open WebUI. Remaining critical gaps are: fix guardrails so only the latest user turn is remotely classified rather than rescanning assistant/document history; calibrate the newly relaxed retrieval thresholds on a sufficiently large human-verified set and measure false-answer rate; make upload jobs durable because interfaces.openai_api stores them in an in-process dictionary and FastAPI BackgroundTasks; add authentication, document ownership, and tenant-scoped database queries; add managed PostgreSQL pooling and migrations; expand upload support beyond the PDF-only API and macOS-only OCR path if DOCX/images and non-Mac deployment are required; detect Docling recovered/dropped table cells and enforce OCR/table/figure fidelity; make page citations open the exact source page in Open WebUI; add production health/readiness endpoints, structured tracing, metrics, rate limits, timeouts, deployment supervision, and backups; and generalize the tool registry beyond the single Tavily MCP configuration.

## Source Nodes

- Pipe,documents,children,agent_progress_missing,orchestration_progress_missing,retrieval_progress_missing,ingestion_progress_missing,_sanitize_messages()