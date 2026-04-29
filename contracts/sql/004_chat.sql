-- Chat history backing the /api/v1/chat/{thread_id}/history endpoint.
-- One row per chat turn (user or assistant). The /api/v1/chat/stream
-- handler inserts the user row before yielding the first SSE frame and
-- the assistant row after the final ``end`` frame, so the persisted log
-- survives restarts even though the in-memory LangGraph checkpoint does
-- not (TM-D5 plan §2 decisions #6/#7).

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.chat_messages (
    id          BIGSERIAL PRIMARY KEY,
    thread_id   TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_created
    ON analytics.chat_messages (thread_id, created_at);
