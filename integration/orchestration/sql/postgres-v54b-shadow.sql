-- AppLab v5.4B Durable Store Shadow
-- PostgreSQL-compatible operational schema.
-- SHADOW_NO_DISPATCH: this schema stores orchestration metadata only.

BEGIN;

CREATE TABLE IF NOT EXISTS applab_store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO applab_store_meta(key, value)
VALUES
    ('schema_version', '1'),
    ('mode', 'SHADOW_NO_DISPATCH'),
    ('authority', 'NONE')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

CREATE TABLE IF NOT EXISTS applab_events (
    event_id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    correlation_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_event_type TEXT NOT NULL,
    repository TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    resolved_sha CHAR(40) NOT NULL,
    admission TEXT NOT NULL CHECK (admission IN ('ADMITTED','REJECTED')),
    payload_sha256 TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (resolved_sha ~ '^[0-9a-f]{40}$')
);

CREATE TABLE IF NOT EXISTS applab_operations (
    operation_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    correlation_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    resolved_sha CHAR(40) NOT NULL,
    applab_sha CHAR(40) NOT NULL,
    operation_class TEXT NOT NULL,
    analysis_mode TEXT NOT NULL,
    queue_key TEXT NOT NULL,
    priority INTEGER NOT NULL CHECK (priority BETWEEN 0 AND 1000),
    authority TEXT NOT NULL CHECK (authority = 'ORCHESTRATION_ONLY'),
    initial_state TEXT NOT NULL,
    current_state TEXT NOT NULL,
    immutable_identity_sha256 TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (resolved_sha ~ '^[0-9a-f]{40}$'),
    CHECK (applab_sha ~ '^[0-9a-f]{40}$')
);

CREATE INDEX IF NOT EXISTS applab_operations_queue_idx
ON applab_operations(queue_key, priority DESC, created_at ASC);

CREATE TABLE IF NOT EXISTS applab_attempts (
    attempt_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES applab_operations(operation_id),
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    executor TEXT NOT NULL,
    state TEXT NOT NULL,
    failure_class TEXT NOT NULL,
    retryable BOOLEAN NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(operation_id, attempt_number)
);

CREATE TABLE IF NOT EXISTS applab_evidence_refs (
    evidence_ref_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES applab_operations(operation_id),
    attempt_id TEXT REFERENCES applab_attempts(attempt_id),
    artifact_name TEXT NOT NULL,
    evidence_class TEXT NOT NULL,
    producer TEXT NOT NULL,
    registry_state TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    storage_uri TEXT NOT NULL,
    repository TEXT NOT NULL,
    resolved_sha CHAR(40) NOT NULL,
    applab_sha CHAR(40) NOT NULL,
    retention_class TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    payload_sha256 TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (resolved_sha ~ '^[0-9a-f]{40}$'),
    CHECK (applab_sha ~ '^[0-9a-f]{40}$')
);

CREATE INDEX IF NOT EXISTS applab_evidence_operation_idx
ON applab_evidence_refs(operation_id, created_at ASC);

CREATE TABLE IF NOT EXISTS applab_operation_transitions (
    transition_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES applab_operations(operation_id),
    sequence_number INTEGER NOT NULL CHECK (sequence_number >= 1),
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    actor TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    metadata_digest_sha256 TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(operation_id, sequence_number)
);

CREATE INDEX IF NOT EXISTS applab_transition_operation_idx
ON applab_operation_transitions(operation_id, sequence_number ASC);

CREATE OR REPLACE FUNCTION applab_reject_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'AppLab v5.4B append-only table % rejects %', TG_TABLE_NAME, TG_OP;
END;
$$;

CREATE OR REPLACE FUNCTION applab_guard_operation_identity()
RETURNS trigger
LANGUAGE plpgsql
AS $applab$
BEGIN
    IF NEW.operation_id IS DISTINCT FROM OLD.operation_id
       OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
       OR NEW.correlation_id IS DISTINCT FROM OLD.correlation_id
       OR NEW.repository IS DISTINCT FROM OLD.repository
       OR NEW.source_ref IS DISTINCT FROM OLD.source_ref
       OR NEW.resolved_sha IS DISTINCT FROM OLD.resolved_sha
       OR NEW.applab_sha IS DISTINCT FROM OLD.applab_sha
       OR NEW.operation_class IS DISTINCT FROM OLD.operation_class
       OR NEW.analysis_mode IS DISTINCT FROM OLD.analysis_mode
       OR NEW.queue_key IS DISTINCT FROM OLD.queue_key
       OR NEW.priority IS DISTINCT FROM OLD.priority
       OR NEW.authority IS DISTINCT FROM OLD.authority
       OR NEW.initial_state IS DISTINCT FROM OLD.initial_state
       OR NEW.immutable_identity_sha256 IS DISTINCT FROM OLD.immutable_identity_sha256
       OR NEW.payload IS DISTINCT FROM OLD.payload
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'AppLab v5.4B operation immutable identity mutation rejected';
    END IF;

    IF NEW.current_state IS DISTINCT FROM OLD.current_state
       AND NOT EXISTS (
           SELECT 1
           FROM applab_operation_transitions t
           WHERE t.operation_id = OLD.operation_id
             AND t.from_state = OLD.current_state
             AND t.to_state = NEW.current_state
             AND t.sequence_number = (
                 SELECT MAX(t2.sequence_number)
                 FROM applab_operation_transitions t2
                 WHERE t2.operation_id = OLD.operation_id
             )
       )
    THEN
        RAISE EXCEPTION 'AppLab v5.4B operation state update requires matching transition';
    END IF;

    NEW.updated_at := NOW();
    RETURN NEW;
END;
$applab$;

DROP TRIGGER IF EXISTS applab_events_append_only_u ON applab_events;
DROP TRIGGER IF EXISTS applab_events_append_only_d ON applab_events;
CREATE TRIGGER applab_events_append_only_u
BEFORE UPDATE ON applab_events
FOR EACH ROW EXECUTE FUNCTION applab_reject_mutation();
CREATE TRIGGER applab_events_append_only_d
BEFORE DELETE ON applab_events
FOR EACH ROW EXECUTE FUNCTION applab_reject_mutation();

DROP TRIGGER IF EXISTS applab_attempts_append_only_u ON applab_attempts;
DROP TRIGGER IF EXISTS applab_attempts_append_only_d ON applab_attempts;
CREATE TRIGGER applab_attempts_append_only_u
BEFORE UPDATE ON applab_attempts
FOR EACH ROW EXECUTE FUNCTION applab_reject_mutation();
CREATE TRIGGER applab_attempts_append_only_d
BEFORE DELETE ON applab_attempts
FOR EACH ROW EXECUTE FUNCTION applab_reject_mutation();

DROP TRIGGER IF EXISTS applab_evidence_append_only_u ON applab_evidence_refs;
DROP TRIGGER IF EXISTS applab_evidence_append_only_d ON applab_evidence_refs;
CREATE TRIGGER applab_evidence_append_only_u
BEFORE UPDATE ON applab_evidence_refs
FOR EACH ROW EXECUTE FUNCTION applab_reject_mutation();
CREATE TRIGGER applab_evidence_append_only_d
BEFORE DELETE ON applab_evidence_refs
FOR EACH ROW EXECUTE FUNCTION applab_reject_mutation();

DROP TRIGGER IF EXISTS applab_transitions_append_only_u ON applab_operation_transitions;
DROP TRIGGER IF EXISTS applab_transitions_append_only_d ON applab_operation_transitions;
CREATE TRIGGER applab_transitions_append_only_u
BEFORE UPDATE ON applab_operation_transitions
FOR EACH ROW EXECUTE FUNCTION applab_reject_mutation();
CREATE TRIGGER applab_transitions_append_only_d
BEFORE DELETE ON applab_operation_transitions
FOR EACH ROW EXECUTE FUNCTION applab_reject_mutation();

DROP TRIGGER IF EXISTS applab_operations_identity_guard ON applab_operations;
CREATE TRIGGER applab_operations_identity_guard
BEFORE UPDATE ON applab_operations
FOR EACH ROW EXECUTE FUNCTION applab_guard_operation_identity();

COMMIT;
