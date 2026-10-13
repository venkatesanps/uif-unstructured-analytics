---
name: snowflake-ddl
description: Keep sql/snowflake/core.sql in step with the contracts and sql/duckdb/core.sql - generate or diff CORE tables, MERGE tasks and mart views from the registry. Use when a contract, table or doc type changes.
---

# Snowflake DDL sync

1. Source of truth for columns is `src/uif/contracts.py` (+ the row shaping in `steps/publish.py`).
2. Diff three things and list mismatches before editing:
   - pydantic fields vs `sql/duckdb/core.sql` columns
   - `sql/duckdb/core.sql` vs `sql/snowflake/core.sql` (names must match; types map
     VARCHAR→STRING, JSON→VARIANT, DOUBLE→FLOAT)
   - every table in `steps/publish.py` has a MERGE task in Snowflake (copy the EXTRACTED_FACT pattern:
     stream on UIF_RAW.PUBLISHED filtered by `table_name`, QUALIFY latest per key)
3. For each doc type with analyst-facing marts, mirror the DuckDB view in `UIF_MART` using
   `value_norm:path::TYPE` instead of `->>`.
4. Governance: every new text column that can carry document content gets the
   `UIF_CORE.MASK_EVIDENCE` masking policy; tag tables with `UIF_CORE.SENSITIVITY`.
5. Run `make test` (DuckDB side). Snowflake DDL is reviewed by a human before Phase 2 deploy;
   do not execute it against any account from this skill.
