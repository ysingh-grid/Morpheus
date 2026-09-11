---
type: "query"
date: "2026-09-08T16:14:42.114666+00:00"
question: "How are tables processed? Are they broken into chunks?"
contributor: "graphify"
source_nodes: ["_table_metadata,_table_chunk_records,TableRecord,table_chunks,hybrid_search_and_join"]
---

# Q: How are tables processed? Are they broken into chunks?

## Answer

Yes. Docling TableItems become one canonical tables row with full markdown, plus row-safe table_chunks of at most 250 tokens that never split a row. Parent markdown replaces the table with [Table table-id]. table_chunks are full-text indexed only, not embedded; hybrid search can hit them and join back to the parent. get_full_table hydrates the full markdown when the agent asks.

## Source Nodes

- _table_metadata,_table_chunk_records,TableRecord,table_chunks,hybrid_search_and_join