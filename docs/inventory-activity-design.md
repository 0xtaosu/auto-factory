# Inventory Activity MVP v0.1

Approved direction: reuse Python/FastAPI/SQLite and React. Backend owned by Codex;
frontend implementation delegated to Grok at the user's request. No LLM in the
analysis path. Existing health algorithms remain historical code, not the default API.

## Architecture and implementation sequence

1. Add an isolated `backend/app/inventory_activity` pipeline: load ERP, normalize,
   calculate metrics, evaluate YAML policy, export JSON/CSV/Turtle and quality report.
2. Preserve source bytes, file SHA256, sheet, row, typed raw values and normalized
   values. Invalid rows remain in raw records with issues. Exact duplicate rows
   (including source sequence) are retained as evidence but counted once; matching
   business fields with different sequence numbers are only flagged, not dropped.
3. Compute three required metrics and optional flow totals with Decimal arithmetic.
   Missing amount does not invalidate an otherwise valid event; value aggregates
   are unavailable if an included amount is missing. Missing supplier creates no
   fictitious Supplier. Conflicting units block quantity aggregation for that SKU.
4. Calculate recency using all accepted events on/before observation date. Frequency
   uses the requested window; annual flows use observation calendar year. Record
   actual source date range separately from requested windows. Same-day latest events
   are all retained; a stable source-row tie-break selects one display event only.
5. Snapshot policy content and its hash, input hash, observation date and windows in
   each run. Stable event identifiers are scoped to the source workbook, sheet, row.
6. Export from one result model; RDF contains evidence links for all observations.
   Run automated boundary, invalid-input, round-trip RDF/SPARQL and API tests, then
   run the real workbook and generate the report without forcing expected counts.
7. Grok replaces the default frontend with activity overview, searchable/filterable
   assessment list, source explanation and downloads. Integrate and build it.

## Business boundaries

Only `InactiveMaterialCandidate` / 长期无交易物料候选 is emitted for policy matches.
`ActiveMaterial` means below this policy threshold, not healthy inventory.
No balances, ITR, health scores, inventory valuation or APS imports. No frozen L1
definitions were found locally; a diagnostic-support link to M6-01-02 is added
without creating or redefining its hierarchy. IOF alignment uses a documented
reference only after verifying the upstream identifier, not a blanket import.
Unobserved materials and 365+ day population cannot be completely observed.
Observation dates outside the declared data window are rejected to avoid assuming
no transactions after coverage. Defaults are in configuration, never ontology.

## API contract (frontend implementation contract)

All endpoints below use `/api/activity`. Error responses use FastAPI `detail`.

- `GET /config`: `{observation_date, data_window_start, data_window_end,
  frequency_window_start, frequency_window_end, policy: {policy_id, policy_name,
  metric, operator, threshold_value, threshold_unit, effective_from, effective_to,
  material_category}}`.
- `POST /jobs`: multipart `file`, optional `observation_date` (ISO), optional
  `threshold_days` (nonnegative integer). Returns `{job_id,status}`. Processing is
  synchronous; status is `completed` or `failed`.
- `GET /jobs/{id}`: `{job_id,filename,status,created_at,data_quality,error}`.
  Failed job error is `{message,details}`. A failed analysis must not show healthy zero.
- `GET /jobs/{id}/overview`: `{observation_date,data_window_start,data_window_end,
  policy, counts: {total_records,valid_records,invalid_records,material_count,
  inbound_count,outbound_count,duplicate_count,anomaly_record_count,
  inactive_candidate_count,ge_90_count,ge_180_count},
  days_since_last_movement: {min,median,p75,p90,max}, limitations: [string],
  baseline_comparison: [{metric,expected,actual,diff,reason}]}`.
- `GET /jobs/{id}/assessments?q=&inactive_only=false&offset=0&limit=50`:
  `{total,items:[assessment]}`. `q` searches material code/name; limit <= 500.
- Assessment fields: `assessment_id, material_code, material_name,
  material_specification, material_category, unit, observation_date,
  last_movement_date, days_since_last_movement, movement_frequency,
  annual_outbound_quantity, policy_id, threshold_value, inactive_candidate,
  classification, last_movement_event_ids, metric_observation_ids`.
  Quantities/amounts are decimal strings or null; recency may be null if not observed.
- `GET /jobs/{id}/materials/{code}/explanation`:
  `{assessment, policy, metric_observations:[...], last_movement_events:[...],
  source_records:[...], explanation, limitations:[string]}`.
  Movement fields include `movement_id, source_record_id, transaction_date,
  transaction_type` (`inbound`/`outbound`), `quantity, amount, department, supplier`.
  Source records include `source_record_id, source_file_sha256, source_filename,
  sheet_name, excel_row, raw_values, normalized_values, issues`.
- `GET /jobs/{id}/download/{format}`: `format` is `json`, `csv`, `ttl`, `report`.
  JSON is full result model, CSV assessments, TTL full graph, report Markdown.

UI must state that available data cannot establish positive current stock or a
complete 365+ day population. Display file failures, loading, empty search and null
metrics explicitly. No LLM/health score/obsolete inventory copy. Use existing React
and lucide, responsive Chinese UI, no new UI framework required.

## Validation

179/180/181-day boundaries, inbound-only/outbound-only, same-day ties, Dec 31,
invalid code/date/type/negative/nonfinite numeric input, duplicate identity,
missing amount/supplier, future-event exclusion, unit conflicts, repeated-run IDs,
policy snapshot changes, API persistence/downloads, RDF paths and SPARQL queries.
Baseline: 12,794 events; 820 materials; 5,194 inbound; 7,600 outbound; 13 candidates.
Real GC010 last movement is 2025-12-08, 23 days; the 217-day example is illustrative.
