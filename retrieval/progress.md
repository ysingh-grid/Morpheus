# Retrieval Progress

## Completed

- Added the PostgreSQL and pgvector schema in `schema.sql`.
- Added normalized relational storage for documents, parents, figures, tables, and table chunks.
- Added `children` storage with `vector(1536)` Gemini embeddings and generated PostgreSQL full-text content.
- Added HNSW cosine vector search, full-text GIN search, and foreign-key lookup indexes.
- Added `ingest_bundle(bundle_json)` to embed children with the shared Gemini OpenAI-compatible client and atomically load the complete normalized bundle.
- Added `hybrid_search_and_join(query, top_k)` with one PostgreSQL RRF CTE that fuses vector and full-text rankings, then joins children to parents, figures, tables, and table chunks in the same query.
- Added FlashRank (`ms-marco-MiniLM-L-12-v2`) as the CPU-compatible reranking stage.
- Replaced raw lexical parsing with `websearch_to_tsquery` and added table-chunk full-text retrieval, so table-only numeric/unit matches can retrieve their owning parents and participate in reranking.
- Added content-derived document IDs to prevent same-name upload collisions and limited reranker table input to the highest-scoring matched table chunk.
- Added static retrieval-contract coverage; the project test suite passes.

## Missing

- Provision PostgreSQL with the pgvector extension and configure `DATABASE_URL`.
- Run `initialize_schema()`, then perform a live schema, ingest, and hybrid-retrieval integration test with the IFC annual-report bundle.
- Add database migrations and a managed connection pool before production deployment.

## Known Constraints

- The embedding schema is fixed at 1,536 dimensions and requires all stored/query embeddings to use the same Gemini embedding model and dimension.
- FlashRank downloads and caches its ONNX model on first retrieval request.
- pgvector HNSW filtering must be benchmarked with document/tenant filters before production; filtered approximate search can require iterative scans or partitioning to preserve recall.
- PostgreSQL remains the only storage and retrieval backend; the code does not require or use a separate vector database.
