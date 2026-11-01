
# SkyPoints Loyalty ETL

Python/PostgreSQL reference implementation for the Incubyte Data Engineer assessment. It ingests member-profile files and a semi-structured redemption JSON feed, validates records, preserves raw inputs, stages accepted profiles, publishes valid profile changes and stores redemption transactions.

## Batch processing

Each source file/feed is processed as an independent batch:

1. Calculate a SHA-256 checksum and derive a batch key from feed type, filename and checksum.
2. Register the batch in `skypoints.ingestion_batches`.
3. Mark it `PROCESSING`.
4. Preserve raw input with its batch ID.
5. Write accepted profile rows to staging and invalid rows/issues to audit tables.
6. Publish valid profile changes or redemption transactions.
7. Mark the batch `SUCCEEDED` in the same transaction as its data publication.

If processing fails, the data transaction rolls back and the batch is marked `FAILED`. Failed batches can be retried. An already successful identical file is skipped. A changed file checksum creates a new batch even when its filename is unchanged.

The source does not currently provide a stable batch ID, so the replay key uses feed type + filename + checksum. If the source system supplies a batch ID in future, use that as the primary replay identifier. A corrected file with different contents is treated as a new delivery.

## Scope and assumptions

- Each available configured feed is processed independently. A run can process one or several profile files and/or the redemption JSON; missing feeds are skipped. At least one feed must be present.
- This is bounded file/batch processing, not a continuously running streaming application.
- The existing assessment interpretation is retained: `Member Name` is the target key and `Enrollment Date` is the primary recency proxy. These are assessment assumptions, not ideal real-world identity/update fields.
- `AU` is routed to the Australia target (`table_aus`); the source country value is retained.
- `txn_id` is unique in `fact_redemptions`. Identical transaction replays are treated as successfully processed without inserting a second fact; conflicting reuse of a transaction ID is recorded as a rejected issue and is not silently overwritten. Newly inserted facts carry the current `ingestion_batch_id`. Older facts remain unmodified and may have a NULL batch ID because they predate batch tracking.
- `data/redemptions_sample.json` is an illustrative fixture, not the original production feed.

## Project files

```text
main.py
src/utils.py
sql/01_ddl_tables.sql
tests/test_pipeline.py
data/
requirements.txt
```

## Setup

Python 3.10+ and PostgreSQL are required.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# On the local Mac setup used for this assessment, the default connection is:
# postgresql+psycopg2://<your-mac-user>@localhost:5432/skypoints_db
# Override only if your PostgreSQL connection requires different settings:
# export DATABASE_URL='postgresql+psycopg2://USER:PASSWORD@localhost:5432/skypoints_db'
```

Apply the schema:

```bash
psql -d skypoints_db -f sql/01_ddl_tables.sql
```

The DDL is additive and does not drop or truncate existing tables. Back up an existing database before applying schema changes.

Run tests and pipeline:

```bash
python -m pytest -v
python main.py
```

Set `DATA_DIR` to change the profile input directory, or `REDEMPTION_FILE` to select another redemption JSON file.

## Tables

- `ingestion_batches`: batch identity, checksum, lifecycle status, timestamps and record counts. For redemption batches, counts refer to processed transaction candidates and rejected transaction/feed entries; exact existing transaction replays count as processed.
- `raw_member_profiles`: original profile rows with batch lineage.
- `stg_member_profiles`: standardized accepted profile rows with batch lineage.
- `table_usa`, `table_ind`, `table_aus`, `table_phil`, `table_can`: country-specific published profiles.
- `raw_redemptions_json`: original JSON objects with batch lineage.
- `fact_redemptions`: flattened transaction records with batch lineage.
- `removed_records`: rejected profile rows and reasons.
- `data_quality_issues`: non-blocking profile warnings.
- `redemption_issues`: rejected/conflicting redemption feed or transaction issues.

## Operational behaviour and limitations

- Each feed commits independently. A later failure does not roll back earlier successful batches.
- Normal runs do not truncate historical raw, staging, reject, issue or target data.
- A batch's `SUCCEEDED` status is committed atomically with its database writes.
- The implementation reads each profile file into pandas memory and uses PostgreSQL inserts/upserts. It is a small-data assessment implementation, not evidence of very-high-volume throughput.
- A production-scale design would add durable object storage, bulk loading (for example PostgreSQL `COPY`), partitioning, distributed processing where justified, monitoring, alerting and deployment-level concurrency controls.
- If a process is forcibly terminated while its batch is `PROCESSING`, inspect that batch and reset it to `FAILED` before retrying. The code deliberately does not assume that an active batch is abandoned.
- This implementation does not add a distributed scheduler or streaming platform.

## Tests

Unit tests cover date normalization, derived fields, profile validation, redemption flattening/validation, batch-key determinism, redemption insert parameter binding, exact duplicate handling and batch count consistency. The test suite uses a fake database connection for persistence-path unit tests; it is not a substitute for PostgreSQL integration tests. Run integration tests against a disposable PostgreSQL database before deployment.
