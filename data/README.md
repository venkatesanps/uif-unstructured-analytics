# data/

- `merchant_master.csv` — synthetic merchant master (written by `uif synth`); the resolver matches
  against it. Phase 2 replaces it with a Snowflake lookup.
- `reference/reason_codes.csv` — reason-code lookup used by schema rules (`in_ref`, `ref_pair`) and the
  dispute marts. **Illustrative only:** the codes are real network codes, but `required_evidence` is a
  simplified placeholder, not the networks' compelling-evidence rules. Replace it with the version your
  disputes team maintains before using the evidence-completeness mart for decisions.
- `reference/dispute_outcomes.csv` — synthetic stand-in for the dispute system's case outcomes
  (written by `uif synth`). In Snowflake this is a join to the real dispute table.
