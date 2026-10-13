-- Snowflake RAW -> CORE for UIF. Phase 2 deliverable; kept in step with sql/duckdb/core.sql.
-- Replace <...> placeholders. Database/schema names are suggestions.

CREATE SCHEMA IF NOT EXISTS UIF_RAW;
CREATE SCHEMA IF NOT EXISTS UIF_CORE;
CREATE SCHEMA IF NOT EXISTS UIF_MART;

-- RAW: every NDJSON line the StageWarehouse writes, untouched ------------------
CREATE OR REPLACE STAGE UIF_RAW.PUBLISH_STAGE
  URL = 's3://<bucket>/<prefix>/publish/'
  STORAGE_INTEGRATION = <uif_s3_integration>
  FILE_FORMAT = (TYPE = JSON);

CREATE TABLE IF NOT EXISTS UIF_RAW.PUBLISHED (
  table_name STRING,
  payload    VARIANT,
  file_name  STRING,
  loaded_at  TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE PIPE UIF_RAW.PUBLISHED_PIPE AUTO_INGEST = TRUE AS
  COPY INTO UIF_RAW.PUBLISHED (table_name, payload, file_name)
  FROM (SELECT $1:_table::STRING, $1, METADATA$FILENAME FROM @UIF_RAW.PUBLISH_STAGE);

CREATE OR REPLACE STREAM UIF_RAW.PUBLISHED_STREAM ON TABLE UIF_RAW.PUBLISHED APPEND_ONLY = TRUE;

-- CORE ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS UIF_CORE.DOC_ENVELOPE (
  doc_id STRING PRIMARY KEY, content_sha256 STRING, source_group STRING, source_system STRING,
  submitter STRING, received_ts TIMESTAMP_TZ, file_name STRING, mime_type STRING, storage_uri STRING,
  page_count INT, language STRING, sensitivity_tier STRING
);
CREATE TABLE IF NOT EXISTS UIF_CORE.DOC_CHUNK (
  chunk_id STRING PRIMARY KEY, doc_id STRING, page INT, text_tokenized STRING
  -- , embedding VECTOR(FLOAT, 1024)   -- Phase 3, via Cortex EMBED or Bedrock
);
CREATE TABLE IF NOT EXISTS UIF_CORE.GUARD_FINDING (doc_id STRING, seq INT, kind STRING, page INT, token STRING);
CREATE TABLE IF NOT EXISTS UIF_CORE.DOC_CLASSIFICATION (
  doc_id STRING PRIMARY KEY, doc_type STRING, confidence FLOAT, taxonomy_version STRING, method STRING, model_id STRING
);
CREATE TABLE IF NOT EXISTS UIF_CORE.EXTRACTOR_RUN (
  run_id STRING PRIMARY KEY, doc_id STRING, agent STRING, model_id STRING, prompt_version STRING,
  tokens_in INT, tokens_out INT, latency_ms INT, started_ts TIMESTAMP_TZ
);
CREATE TABLE IF NOT EXISTS UIF_CORE.ENTITY_LINK (
  doc_id STRING PRIMARY KEY, merchant_id STRING, mid STRING, legal_name STRING, match_method STRING, match_score FLOAT
);
CREATE TABLE IF NOT EXISTS UIF_CORE.EXTRACTED_FACT (
  fact_id STRING PRIMARY KEY, doc_id STRING, schema_name STRING, schema_version STRING, field_path STRING,
  value_raw VARIANT, value_norm VARIANT, data_type STRING, confidence FLOAT, evidence_page INT,
  evidence_quote STRING, run_id STRING, review_status STRING, review_reasons VARIANT
);
CREATE TABLE IF NOT EXISTS UIF_CORE.REVIEW_TASK (
  task_id STRING PRIMARY KEY, doc_id STRING, fact_ids VARIANT, reason STRING, created_ts TIMESTAMP_TZ,
  decision STRING, corrected_value VARIANT
);

-- MERGE task (one shown; repeat per table, or generate with the snowflake-ddl skill) ----
CREATE OR REPLACE TASK UIF_CORE.MERGE_EXTRACTED_FACT
  WAREHOUSE = <wh> SCHEDULE = '5 MINUTE'
  WHEN SYSTEM$STREAM_HAS_DATA('UIF_RAW.PUBLISHED_STREAM')
AS
MERGE INTO UIF_CORE.EXTRACTED_FACT t
USING (
  SELECT payload:fact_id::STRING fact_id, payload:doc_id::STRING doc_id, payload:schema_name::STRING schema_name,
         payload:schema_version::STRING schema_version, payload:field_path::STRING field_path,
         PARSE_JSON(payload:value_raw::STRING) value_raw, PARSE_JSON(payload:value_norm::STRING) value_norm,
         payload:data_type::STRING data_type, payload:confidence::FLOAT confidence,
         payload:evidence_page::INT evidence_page, payload:evidence_quote::STRING evidence_quote,
         payload:run_id::STRING run_id, payload:review_status::STRING review_status,
         payload:review_reasons review_reasons
  FROM UIF_RAW.PUBLISHED_STREAM WHERE table_name = 'extracted_fact'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY fact_id ORDER BY loaded_at DESC) = 1
) s ON t.fact_id = s.fact_id
WHEN MATCHED THEN UPDATE SET value_raw = s.value_raw, value_norm = s.value_norm, confidence = s.confidence,
  evidence_page = s.evidence_page, evidence_quote = s.evidence_quote, run_id = s.run_id,
  review_status = s.review_status, review_reasons = s.review_reasons, schema_version = s.schema_version
WHEN NOT MATCHED THEN INSERT VALUES (s.fact_id, s.doc_id, s.schema_name, s.schema_version, s.field_path,
  s.value_raw, s.value_norm, s.data_type, s.confidence, s.evidence_page, s.evidence_quote, s.run_id,
  s.review_status, s.review_reasons);

-- Governance ----------------------------------------------------------------
CREATE TAG IF NOT EXISTS UIF_CORE.SENSITIVITY ALLOWED_VALUES 'internal', 'confidential', 'restricted';

-- Evidence quotes can carry business-confidential text: show them to reviewer roles only.
CREATE OR REPLACE MASKING POLICY UIF_CORE.MASK_EVIDENCE AS (val STRING) RETURNS STRING ->
  CASE WHEN IS_ROLE_IN_SESSION('UIF_REVIEWER') OR IS_ROLE_IN_SESSION('UIF_ENGINEER') THEN val
       ELSE '***' END;
ALTER TABLE UIF_CORE.EXTRACTED_FACT MODIFY COLUMN evidence_quote SET MASKING POLICY UIF_CORE.MASK_EVIDENCE;
ALTER TABLE UIF_CORE.DOC_CHUNK      MODIFY COLUMN text_tokenized  SET MASKING POLICY UIF_CORE.MASK_EVIDENCE;
