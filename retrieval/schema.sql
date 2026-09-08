CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    content_sha256 TEXT,
    source_path TEXT NOT NULL,
    summary TEXT NOT NULL
);

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS content_sha256 TEXT;

CREATE TABLE IF NOT EXISTS parents (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    parent_text TEXT NOT NULL,
    page_numbers INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[],
    figure_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    table_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]
);

CREATE TABLE IF NOT EXISTS figures (
    id TEXT NOT NULL,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    caption TEXT NOT NULL,
    bounding_boxes JSONB NOT NULL DEFAULT '[]'::JSONB,
    PRIMARY KEY (doc_id, id)
);

CREATE TABLE IF NOT EXISTS figure_images (
    doc_id TEXT NOT NULL,
    figure_id TEXT NOT NULL,
    image_bytes BYTEA NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'image/png',
    PRIMARY KEY (doc_id, figure_id),
    FOREIGN KEY (doc_id, figure_id) REFERENCES figures(doc_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tables (
    id TEXT NOT NULL,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    markdown TEXT NOT NULL,
    heading TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '',
    bounding_boxes JSONB NOT NULL DEFAULT '[]'::JSONB,
    row_count INTEGER NOT NULL,
    column_count INTEGER NOT NULL,
    chunk_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    PRIMARY KEY (doc_id, id)
);

CREATE TABLE IF NOT EXISTS table_chunks (
    id TEXT NOT NULL,
    table_id TEXT NOT NULL,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    row_start INTEGER NOT NULL,
    row_end INTEGER NOT NULL,
    text_with_context TEXT NOT NULL,
    page_numbers INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[],
    fts_content TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', text_with_context)
    ) STORED,
    PRIMARY KEY (doc_id, id),
    FOREIGN KEY (doc_id, table_id) REFERENCES tables(doc_id, id) ON DELETE CASCADE
);

ALTER TABLE table_chunks
    ADD COLUMN IF NOT EXISTS fts_content TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', text_with_context)
    ) STORED;

ALTER TABLE table_chunks
    ADD COLUMN IF NOT EXISTS page_numbers INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[];

CREATE TABLE IF NOT EXISTS children (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    text_with_context TEXT NOT NULL,
    retrieval_text TEXT NOT NULL,
    page_numbers INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[],
    embedding VECTOR(1536) NOT NULL,
    fts_content TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', text_with_context)
    ) STORED,
    retrieval_fts_content TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', retrieval_text)
    ) STORED
);

ALTER TABLE parents
    ADD COLUMN IF NOT EXISTS page_numbers INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[];

ALTER TABLE children
    ADD COLUMN IF NOT EXISTS page_numbers INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[];

ALTER TABLE children
    ADD COLUMN IF NOT EXISTS retrieval_text TEXT NOT NULL DEFAULT '';

UPDATE children
SET retrieval_text = CASE
    WHEN text_with_context LIKE 'Document summary:%%'
         AND STRPOS(text_with_context, E'\n\n') > 0
    THEN SUBSTRING(
        text_with_context FROM STRPOS(text_with_context, E'\n\n') + 2
    )
    ELSE text_with_context
END
WHERE retrieval_text = '';

ALTER TABLE children
    ADD COLUMN IF NOT EXISTS retrieval_fts_content TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', retrieval_text)
    ) STORED;

CREATE TABLE IF NOT EXISTS user_facts (
    user_id TEXT NOT NULL,
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    category TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, fact_key)
);

CREATE TABLE IF NOT EXISTS user_sessions (
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    conversation_summary TEXT NOT NULL DEFAULT '',
    document_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, session_id)
);

ALTER TABLE user_sessions
    ADD COLUMN IF NOT EXISTS document_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

CREATE TABLE IF NOT EXISTS agent_tool_results (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS parents_doc_id_idx ON parents(doc_id);
CREATE INDEX IF NOT EXISTS documents_content_sha256_idx ON documents(content_sha256);
CREATE INDEX IF NOT EXISTS figures_doc_id_idx ON figures(doc_id);
CREATE INDEX IF NOT EXISTS tables_doc_id_idx ON tables(doc_id);
CREATE INDEX IF NOT EXISTS table_chunks_table_id_idx ON table_chunks(doc_id, table_id);
CREATE INDEX IF NOT EXISTS table_chunks_fts_content_gin_idx
    ON table_chunks USING gin (fts_content);
CREATE INDEX IF NOT EXISTS children_parent_id_idx ON children(parent_id);
CREATE INDEX IF NOT EXISTS children_doc_id_idx ON children(doc_id);
CREATE INDEX IF NOT EXISTS children_embedding_hnsw_idx
    ON children USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS children_fts_content_gin_idx
    ON children USING gin (fts_content);
CREATE INDEX IF NOT EXISTS children_retrieval_fts_content_gin_idx
    ON children USING gin (retrieval_fts_content);
CREATE INDEX IF NOT EXISTS user_facts_user_id_idx ON user_facts(user_id);
CREATE INDEX IF NOT EXISTS user_sessions_user_id_idx ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS user_sessions_document_ids_gin_idx ON user_sessions USING gin (document_ids);
CREATE INDEX IF NOT EXISTS agent_tool_results_session_id_idx ON agent_tool_results(session_id);
CREATE INDEX IF NOT EXISTS figure_images_doc_id_idx ON figure_images(doc_id);
