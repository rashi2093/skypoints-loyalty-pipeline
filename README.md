# SkyPoints Loyalty ETL

A PostgreSQL/Python reference implementation for the Incubyte Data Engineer assessment. It ingests country member-profile files, validates and stages records, derives Age and Stale Member, routes the latest member record to a country target, and parses a JSON redemption feed into a queryable transaction table.

## Assessment alignment and explicit assumptions

- The assessment data dictionary marks **Member Name** as the key and **Member ID** as non-key. This implementation partitions latest-record selection by normalized Member Name and uses Member Name as the country-target primary key.
- The assessment says latest record wins but does not define an update timestamp. This implementation uses **Enrollment Date descending** as the primary recency proxy and Last Flight Date descending as a secondary proxy. Enrollment Date is not asserted to be a true profile-update timestamp.
- Member Name is not a globally reliable real-world identifier: two people can share a name. A production source should provide a stable immutable member surrogate key. That key is not supplied in the assessment.
- The assessment's example country code is `AU`; the supplied Australia file is identified as `AUS`. Both are explicitly routed to the Australia target. The source value is retained.
- Post Code appears in the data dictionary but not in the assessment sample layout or the supplied files. It remains nullable.
- `individual_or_corporate` appears in the supplied India data but not in the assessment dictionary. It is retained as an optional source extension, with no fabricated default.
- The assessment JSON sample refers to member ID `223457`, which is not in the supplied profile files. The redemption fact table therefore retains the member ID without inventing a profile match.
- Member ID is not unique in the supplied sample. A join on member ID alone can be ambiguous. A production contract needs a globally unique member key or additional discriminator in the redemption feed.

## Project layout

```text
main.py
src/utils.py
sql/01_ddl_tables.sql
tests/test_pipeline.py
data/USA(in).csv
data/IND(in).csv
data/AUS.xlsx
data/redemptions_sample.json
requirements.txt
```

## Prerequisites

- Python 3.10+
- PostgreSQL
- A database named `skypoints_db` (or set `DATABASE_URL`)

Install dependencies:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create the database schema (the DDL drops and recreates the assessment tables, so use it only when a fresh rebuild is intended):

```bash
psql -d skypoints_db -f sql/01_ddl_tables.sql
```

Configure the connection if needed:

```bash
export DATABASE_URL='postgresql+psycopg2://USER:PASSWORD@localhost:5432/skypoints_db'
```

Run tests and pipeline:

```bash
python -m pytest -v
python main.py
```

## Input feeds

Profile files are configured in `COUNTRY_FILES` in `main.py`. The current reference files are CSV for USA and India and XLSX for Australia. The pipeline checks all configured files before it opens a database transaction. Missing or empty required files fail the run before existing database data is touched.

The redemption feed path defaults to `data/redemptions_sample.json`. Set `REDEMPTION_FILE` to use another JSON file. The loader accepts either one feed object or an array of feed objects. Each feed object has `member_id`, `feed_date`, and a `redemptions` array. Each redemption has `txn_id`, `txn_date`, `partner`, `miles_redeemed`, and `status`.

The sample JSON is a separate input fixture, not hardcoded ETL logic. Replace it with the actual daily feed when available.

## Validation and error handling

- Mandatory Member Name, Member ID and Enrollment Date failures reject the profile row into `removed_records`.
- Field-length checks follow the assessment dictionary: Name 255, ID 18, Tier 5, Agent 255, State 5, Country 5, Active Member 1.
- Optional missing fields remain NULL. Invalid optional dates/text/postcodes are nulled and recorded in `data_quality_issues`; they do not reject the entire member.
- Post Code is validated as up to five digits before conversion to integer. The numeric data type means leading zeroes cannot be preserved; this is inherent in the assessment's INT type.
- Redemption payload and transaction validations are recorded in `redemption_issues`.
- An identical replay of a transaction ID is ignored. A repeated transaction ID with different values is recorded as a conflicting duplicate and is not silently overwritten.

## Database tables

- `raw_member_profiles`: original member source records.
- `stg_member_profiles`: validated and standardized profile records plus derived fields.
- `table_usa`, `table_ind`, `table_aus`, `table_phil`, `table_can`: country-specific latest profile records.
- `raw_redemptions_json`: raw JSON feed payloads, deduplicated by payload hash.
- `fact_redemptions`: flattened transaction-level data.
- `removed_records`: rejected member records and reasons.
- `data_quality_issues`: non-blocking profile warnings.
- `redemption_issues`: rejected or conflicting redemption feed/transaction issues.

## Redemption-to-profile join

The assessment JSON contains `member_id`, so the natural illustrative join is `fact_redemptions.member_id = country_target.member_id`. However, Member ID is not declared a key in the assessment and repeats across the supplied country files. The assessment sample's `223457` also has no matching profile in the supplied data. Therefore, the implementation does not claim a guaranteed one-to-one join. A production feed should carry a globally unique immutable member key (or a documented composite key) to make this relationship reliable.

## Scalability: production design for very high daily volumes

This repository is a correctness-focused local reference implementation; it is **not** a demonstrated billions-of-records-per-day system. The assessment asks us to consider that scale, but does not prescribe a specific cloud platform or explicitly list implementation techniques. A production design should include:

1. **Durable landing/object storage:** store immutable source files and JSON payloads with batch IDs, checksums, arrival timestamps and replay capability.
2. **Bulk ingestion:** use database-native bulk loaders (for example PostgreSQL `COPY`, or the target warehouse's bulk load facility) rather than row-by-row inserts.
3. **Batch/stream processing:** process bounded batches with checkpoints; use distributed processing only when volume and latency justify it.
4. **Partitioning and indexing:** partition large raw/fact tables by ingestion or transaction date; index/cluster on actual filter and join keys after workload testing.
5. **Incremental processing:** process only new or changed batches using source batch IDs, watermarks or CDC; avoid truncating all history on every daily run.
6. **Idempotency:** assign stable batch and transaction identifiers; enforce uniqueness; distinguish identical replays from conflicting duplicates.
7. **Atomic publication:** load into batch-scoped staging, validate counts and quality thresholds, then publish/swap target partitions only after a successful batch.
8. **Observability and recovery:** persist batch status, input/output/reject counts, issue rates, duration, retries and lineage; support safe replay of failed batches.

For this assessment prototype, the code uses a single database transaction and bulk-style `executemany`/`to_sql` calls where practical. It still reads profile files into pandas memory and performs a full profile refresh, so it must not be represented as production-scale execution.

## Demo checklist

1. Show the raw, staging, target and redemption table DDL.
2. Run tests and the pipeline.
3. Query raw/staging/rejected/warning counts.
4. Show Age and Stale Member derivations.
5. Show latest-record routing by Member Name and Enrollment Date.
6. Show the raw JSON payload and flattened redemption rows.
7. Demonstrate a missing-file preflight failure and verify that prior target data remains intact.
8. Demonstrate a malformed optional field warning versus a mandatory-field rejection.
9. Explain the unresolved Member ID join limitation and the production key requirement.
