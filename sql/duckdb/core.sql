-- Local stand-in for Snowflake CORE + MARTS. Same table and column names as sql/snowflake/.

CREATE TABLE IF NOT EXISTS doc_envelope (
  doc_id VARCHAR PRIMARY KEY, content_sha256 VARCHAR, source_group VARCHAR, source_system VARCHAR,
  submitter VARCHAR, received_ts VARCHAR, file_name VARCHAR, mime_type VARCHAR, storage_uri VARCHAR,
  page_count INTEGER, language VARCHAR, sensitivity_tier VARCHAR
);
CREATE TABLE IF NOT EXISTS doc_chunk (
  chunk_id VARCHAR PRIMARY KEY, doc_id VARCHAR, page INTEGER, text_tokenized VARCHAR
);
CREATE TABLE IF NOT EXISTS guard_finding (
  doc_id VARCHAR, seq INTEGER, kind VARCHAR, page INTEGER, token VARCHAR, PRIMARY KEY (doc_id, seq)
);
CREATE TABLE IF NOT EXISTS doc_classification (
  doc_id VARCHAR PRIMARY KEY, doc_type VARCHAR, confidence DOUBLE, taxonomy_version VARCHAR,
  method VARCHAR, model_id VARCHAR
);
CREATE TABLE IF NOT EXISTS extractor_run (
  run_id VARCHAR PRIMARY KEY, doc_id VARCHAR, agent VARCHAR, model_id VARCHAR, prompt_version VARCHAR,
  tokens_in INTEGER, tokens_out INTEGER, latency_ms INTEGER, started_ts VARCHAR
);
CREATE TABLE IF NOT EXISTS entity_link (
  doc_id VARCHAR PRIMARY KEY, merchant_id VARCHAR, mid VARCHAR, legal_name VARCHAR,
  match_method VARCHAR, match_score DOUBLE
);
CREATE TABLE IF NOT EXISTS extracted_fact (
  fact_id VARCHAR PRIMARY KEY, doc_id VARCHAR, schema_name VARCHAR, schema_version VARCHAR,
  field_path VARCHAR, value_raw JSON, value_norm JSON, data_type VARCHAR, confidence DOUBLE,
  evidence_page INTEGER, evidence_quote VARCHAR, run_id VARCHAR, review_status VARCHAR, review_reasons JSON
);
CREATE TABLE IF NOT EXISTS review_task (
  task_id VARCHAR PRIMARY KEY, doc_id VARCHAR, fact_ids JSON, reason VARCHAR, created_ts VARCHAR,
  decision VARCHAR, corrected_value JSON
);

-- REFERENCE (loaded from data/reference/*.csv on connect) ---------------------
CREATE TABLE IF NOT EXISTS ref_reason_code (
  network VARCHAR, reason_code VARCHAR, category VARCHAR, description VARCHAR, required_evidence VARCHAR
);
-- Stand-in for the dispute system's case outcomes (a join to the real table in Snowflake).
CREATE TABLE IF NOT EXISTS dispute_outcome (case_number VARCHAR, outcome VARCHAR);

-- MARTS ---------------------------------------------------------------------

-- One row per processor statement, typed columns, with the merchant it belongs to.
CREATE OR REPLACE VIEW mart_processor_statement AS
SELECT f.doc_id, l.merchant_id, l.legal_name,
  max(CASE WHEN field_path = 'processor_name'    THEN value_norm ->> '$' END)                 AS processor_name,
  max(CASE WHEN field_path = 'statement_period'  THEN value_norm ->> '$.start' END)           AS period_start,
  max(CASE WHEN field_path = 'statement_period'  THEN value_norm ->> '$.end' END)             AS period_end,
  max(CASE WHEN field_path = 'gross_volume'      THEN CAST(value_norm AS DOUBLE) END)         AS gross_volume,
  max(CASE WHEN field_path = 'transaction_count' THEN CAST(value_norm AS BIGINT) END)         AS transaction_count,
  max(CASE WHEN field_path = 'chargeback_count'  THEN CAST(value_norm AS BIGINT) END)         AS chargeback_count,
  max(CASE WHEN field_path = 'total_fees'        THEN CAST(value_norm AS DOUBLE) END)         AS total_fees,
  bool_or(review_status = 'needs_review')                                                    AS has_open_review
FROM extracted_fact f LEFT JOIN entity_link l USING (doc_id)
WHERE schema_name = 'processor_statement'
GROUP BY ALL;

-- Underwriting signal: statement-implied chargeback ratio and effective rate.
CREATE OR REPLACE VIEW mart_underwriting_variance AS
SELECT *,
  round(100.0 * chargeback_count / nullif(transaction_count, 0), 3) AS chargeback_ratio_pct,
  round(100.0 * total_fees / nullif(gross_volume, 0), 3)           AS effective_rate_pct,
  round(gross_volume / nullif(transaction_count, 0), 2)            AS avg_ticket
FROM mart_processor_statement;

-- Risk themes from analyst notes, one row per theme mention.
CREATE OR REPLACE VIEW mart_analyst_themes AS
SELECT f.doc_id, l.merchant_id, l.legal_name, theme.unnest AS theme
FROM extracted_fact f
LEFT JOIN entity_link l USING (doc_id),
UNNEST(CAST(f.value_norm AS VARCHAR[])) AS theme
WHERE f.schema_name = 'risk_analyst_note' AND f.field_path = 'risk_themes';

-- Pipeline quality by doc type.
CREATE OR REPLACE VIEW mart_pipeline_quality AS
SELECT c.doc_type, count(DISTINCT f.doc_id) AS docs, count(*) AS facts,
  round(avg(CASE WHEN f.review_status = 'auto_accepted' THEN 1 ELSE 0 END), 3) AS auto_accept_rate,
  round(avg(f.confidence), 3) AS avg_confidence
FROM extracted_fact f JOIN doc_classification c USING (doc_id)
GROUP BY c.doc_type;

-- Open review queue.
CREATE OR REPLACE VIEW v_review_queue AS
SELECT t.task_id, t.doc_id, e.file_name, c.doc_type, t.reason, t.created_ts
FROM review_task t JOIN doc_envelope e USING (doc_id) LEFT JOIN doc_classification c USING (doc_id)
WHERE t.decision IS NULL
ORDER BY t.created_ts;

-- Dispute rebuttals -----------------------------------------------------------

-- One row per rebuttal packet.
CREATE OR REPLACE VIEW mart_dispute_packet AS
SELECT f.doc_id, l.merchant_id, l.legal_name,
  any_value(value_norm ->> '$')                      FILTER (WHERE field_path = 'case_number')    AS case_number,
  any_value(value_norm ->> '$')                      FILTER (WHERE field_path = 'card_network')   AS card_network,
  any_value(value_norm ->> '$')                      FILTER (WHERE field_path = 'reason_code')    AS reason_code,
  any_value(TRY_CAST(value_norm AS DOUBLE))          FILTER (WHERE field_path = 'dispute_amount') AS dispute_amount,
  any_value(value_norm ->> '$')                      FILTER (WHERE field_path = 'rebuttal_basis') AS rebuttal_basis,
  any_value(TRY_CAST(value_norm AS VARCHAR[]))       FILTER (WHERE field_path = 'evidence_types') AS evidence_types,
  bool_or(review_status = 'needs_review')                                                         AS has_open_review
FROM extracted_fact f LEFT JOIN entity_link l USING (doc_id)
WHERE f.schema_name = 'dispute_rebuttal'
GROUP BY ALL;

-- Evidence present vs required for the reason code, plus the case outcome.
CREATE OR REPLACE VIEW mart_dispute_evidence AS
WITH j AS (
  SELECT p.*, r.category, r.description AS reason_description,
    string_split(r.required_evidence, ';') AS required_evidence,
    list_filter(string_split(r.required_evidence, ';'),
                x -> NOT list_contains(coalesce(p.evidence_types, []::VARCHAR[]), x)) AS missing_evidence,
    o.outcome
  FROM mart_dispute_packet p
  LEFT JOIN ref_reason_code r ON r.reason_code = p.reason_code AND r.network = p.card_network
  LEFT JOIN dispute_outcome o USING (case_number)
)
SELECT *, round(1 - len(missing_evidence) / nullif(len(required_evidence), 0), 2) AS evidence_completeness
FROM j;

-- Do complete packets win more often? By reason-code category.
CREATE OR REPLACE VIEW mart_dispute_win_rate AS
SELECT category, len(missing_evidence) = 0 AS evidence_complete,
  count(*) AS cases,
  count(*) FILTER (WHERE outcome = 'won') AS won,
  count(*) FILTER (WHERE outcome IN ('won', 'lost')) AS decided,
  round(count(*) FILTER (WHERE outcome = 'won') / nullif(count(*) FILTER (WHERE outcome IN ('won', 'lost')), 0), 2) AS win_rate,
  round(sum(dispute_amount), 2) AS amount_at_stake
FROM mart_dispute_evidence
WHERE category IS NOT NULL
GROUP BY ALL;

-- Which evidence merchants most often fail to send: the list to coach them on.
CREATE OR REPLACE VIEW mart_evidence_gaps AS
SELECT category, gap.unnest AS missing_evidence, count(*) AS packets, round(sum(dispute_amount), 2) AS amount_at_stake
FROM mart_dispute_evidence, UNNEST(missing_evidence) AS gap
GROUP BY ALL
ORDER BY packets DESC, amount_at_stake DESC;
