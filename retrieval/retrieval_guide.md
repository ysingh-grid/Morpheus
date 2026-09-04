# Retrieval Guide

## Purpose

`retrieval.pg_engine` is the standalone retrieval service for normalized RAG
bundles produced by the document preprocessor. It uses one PostgreSQL database
with the `pgvector` extension for both relational source-of-truth data and
vector/full-text retrieval.

The service does not use a separate vector database. PostgreSQL stores parent
text, figures, tables, table rows, child embeddings, and their relationships.

## Configuration

Set these variables in `.env`:

```dotenv
DATABASE_URL=postgresql://user:password@host:5432/morpheus
GEMINI_API_KEY=...
EMBEDDING_MODEL_NAME=gemini-embedding-001
RERANKER_MODEL_NAME=ms-marco-MiniLM-L-12-v2
```

`DATABASE_URL` is required. The configured PostgreSQL instance must permit:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Embeddings use Gemini through the existing OpenAI-compatible `llm_client`.
The schema is fixed to `vector(1536)`, so all document and query embeddings must
be generated with the same model and output dimension.

## Initializing the schema

Call `initialize_schema()` once for a new database:

```bash
uv run --env-file .env python -c "
from retrieval.pg_engine import initialize_schema
initialize_schema()
"
```

The schema creates:

- relational records: `documents`, `parents`, `figures`, `tables`, and
  `table_chunks`;
- retrieval records: `children` with a 1,536-dimensional vector and generated
  `tsvector` content;
- generated full-text content for `table_chunks`, preserving lexical access to
  numeric and unit values that are stored only inside tables;
- an HNSW cosine index for vector search;
- a GIN index for full-text search;
- B-tree indexes for relational lookup paths.

## Loading a preprocessed bundle

Load the JSON returned by `process_document` or written by an extraction runner:

```bash
uv run --env-file .env python -c "
import json
from pathlib import Path
from retrieval.pg_engine import ingest_bundle

bundle = json.loads(Path('dummy_data/ifc-annual-report-2024-financials.chunks.json').read_text())
print(ingest_bundle(bundle))
"
```

The loader:

1. embeds each child’s `text_with_context` with Gemini;
2. opens one PostgreSQL transaction;
3. deletes any existing version of that document;
4. inserts the document, parents, figures, tables, table chunks, and children;
5. commits all records together or rolls them all back.

Do not manually insert only children. A child record is useful only if its
`parent_id` resolves and the parent’s figure/table references are available.

## Data relationships

```text
children (vector + full-text indexed)
  └── parent_id ─────> parents
                         ├── figure_ids[] ──> figures
                         └── table_ids[]  ──> tables
                                              └── table_chunks
```

Children are searched by vector and full-text retrieval. Table chunks are also
searched by full text so numeric/unit values that occur only inside a table can
retrieve their owning parent. Parents and linked assets are fetched atomically as
grounded context after either route produces a candidate.

## Hybrid retrieval flow

Call the public search function:

```bash
uv run --env-file .env python -c "
from retrieval.pg_engine import hybrid_search_and_join

for item in hybrid_search_and_join('What drove IFC financial results?', top_k=5):
    print(item['parent_id'], item['reranker_score'])
"
```

The query follows this fixed sequence:

```text
Question
  → Gemini query embedding
  → PostgreSQL child-vector rank + child/table full-text ranks
  → Reciprocal Rank Fusion (RRF)
  → one SQL join to parent, figures, tables, and table chunks
  → FlashRank reranking
  → grounded evidence returned to the answer-generation layer
```

The lexical paths use `websearch_to_tsquery`, so raw user input can safely use
quoted phrases, `OR`, and `-` exclusion. The vector and lexical paths are fused
by RRF inside one SQL statement. The service does not perform a vector query
followed by a second metadata query; this avoids inconsistent data reads and
excess round trips.

## Result contract

`hybrid_search_and_join()` returns a confidence-gated response:

```python
{
  "status": "grounded | not_found | clarification_needed",
  "message": "...",
  "confidence": {
    "rrf_score": 0.0,
    "vector_distance": 0.0,
    "lexical_match": True,
    "rrf_score_margin": 0.0,
    "reasons": []
  },
  "evidence": []
}
```

Only `grounded` responses contain reranked evidence. `not_found` avoids an unsupported answer; `clarification_needed` asks the user to narrow an ambiguous query. Calibrate the four gates through `RETRIEVAL_MIN_RRF_SCORE`, `RETRIEVAL_MAX_VECTOR_DISTANCE`, and `RETRIEVAL_MIN_RRF_SCORE_MARGIN` after running the benchmark.

Each returned grounded-evidence item contains:

- `chunk_id` and `child_text`: the matched retrieval unit;
- `parent_id` and `parent_text`: the complete source context;
- `document_id`: source document identifier;
- `rrf_score` and `reranker_score`: retrieval and relevance scores;
- `figures`: captions and bounding boxes relevant to the parent;
- `tables`: canonical table Markdown, native heading/caption context, and
  linked row-safe chunks.
- `matched_table_chunks`: the highest-scoring full-text table row/context for
  this parent, when a table caused the lexical hit.

Give the answer-generation LLM the returned evidence, not an unbounded document
dump. Reranking receives the bounded `matched_table_chunks` before parent text,
so table-only numeric evidence is not displaced by unrelated table rows.

## Validation and production safeguards

Before ingesting a bundle, require the preprocessor validation manifest to have
no errors. At minimum, verify:

```text
validation.errors == []
figures_detected == figures_captioned == figures_with_bounding_boxes
tables_detected == tables_exported
figures_unassigned == 0
tables_unassigned == 0
remaining_image_placeholders == 0
tables_split_across_chunks == 0
```

After loading, test three query types against the uploaded source:

1. an exact term/query that should succeed through full-text search;
2. a paraphrased conceptual query that should succeed through vector search;
3. a question requiring prose plus a linked figure or table.

The output is suitable only when the returned parent and linked assets support
the answer visible in the original upload. Structural IDs resolving correctly is
necessary but does not prove table-cell accuracy or caption faithfulness.

## Operational constraints

| Risk | Safeguard |
|---|---|
| Mixed embedding models or dimensions | Version embeddings; re-embed the entire corpus before switching models. |
| HNSW filtered-result recall | Benchmark with real document/tenant filters; tune iterative scans, filter indexes, or partitions before production. |
| Large ingestion batches | Keep embedding batches bounded; load one document transactionally. |
| FlashRank cold start | Preload/cache its ONNX model in the service image or startup lifecycle. |
| Parent/asset over-fetching | Return only the top reranked evidence and select needed table rows before LLM generation. |
| Table extraction errors | Treat preprocessor warnings about dropped/recovered cells as a source-review signal. |

## Troubleshooting

| Symptom | Check |
|---|---|
| `DATABASE_URL must be set` | Configure `DATABASE_URL` in `.env`. |
| `extension "vector" is not available` | Install pgvector on the PostgreSQL server, then rerun schema initialization. |
| Embedding dimension error | Use `gemini-embedding-001` with 1,536 dimensions, or migrate schema and re-embed all rows. |
| No useful lexical results | Inspect generated child/table `fts_content`, language configuration, and exact source terms. |
| Weak semantic results | Verify the query/document use the same embedding model, evaluate child chunk quality, then tune RRF candidate size and reranking. |
| FlashRank first request is slow | Expected model download/cache behavior; prewarm it before serving traffic. |
