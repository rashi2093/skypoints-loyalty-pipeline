# SkyPoints Loyalty ETL

Python/PostgreSQL reference implementation for the Incubyte Data Engineer assessment. The pipeline ingests member-profile files and a semi-structured redemption JSON feed, validates records, preserves raw inputs, stages accepted profiles, publishes country-specific member profiles, and stores redemption transactions.

## 1. Scope and assumptions

- Each available configured feed is processed independently. A run can process one or more profile files and/or the redemption JSON feed. Missing feeds are skipped; at least one feed must be present.
- This is a bounded batch-processing solution, not a continuously running streaming application.
- `Member Name`, normalized by trimming whitespace and ignoring case, is used as the assessment-level identity key for country-level publishing.
- `Member ID` is mandatory and retained as a profile attribute, but is not assumed to be globally unique. The supplied country feeds reuse values such as `1`, `2`, and `3` for different names.
- The source does not provide a reliable profile `updated_at` timestamp or version sequence. The pipeline therefore uses deterministic within-batch selection and batch receipt time for cross-batch recency.
- Country code `AU` is normalized to `AUS` and routed to `table_aus`.
- `data/redemptions_sample.json` is an illustrative fixture, not the original production feed.

These are assessment-level assumptions. Production use requires a reliable, globally unique member identifier and source-controlled update/version information.

## 2. Batch processing

Each source file or feed is processed as an independent batch:

1. Calculate a SHA-256 checksum and derive a batch key from feed type, filename, and checksum.
2. Register the batch in `skypoints.ingestion_batches`.
3. Mark the batch as `PROCESSING`.
4. Preserve raw input with its batch ID.
5. Write accepted profile rows to staging and invalid rows or issues to audit tables.
6. Publish valid profile changes or redemption transactions.
7. Mark the batch as `SUCCEEDED` in the same transaction as its data publication.

If processing fails, the data transaction rolls back and the batch is marked `FAILED`. Failed batches can be retried.

An already successful identical file is skipped. A changed file checksum creates a new batch, even if the filename is unchanged. A file with identical contents but a different filename is also treated as a separate delivery.

The source does not currently provide a stable batch ID, so the replay key uses feed type, filename, and checksum. If the source system supplies a batch ID in future, it can be incorporated as the primary replay identifier.

Each feed commits independently. A failure in a later batch does not roll back earlier successful batches.

## 3. Member identity and country transfers

The assessment implementation uses normalized `Member Name` as the identity key for country-level publishing.

- Names are trimmed and compared case-insensitively.
- `Member ID` is retained as a profile attribute and is not used as a globally unique identity.
- When a member's normalized name appears in another country, the pipeline checks existing country assignments before moving the record.
- A transfer is performed only when the matching identity is unambiguous.
- If the same normalized name appears across multiple country tables, the pipeline does not automatically move or delete those records. The ambiguity is retained for review.

Names are not reliable global identifiers: different people can share a name, and one person's name can change or be represented differently across feeds. The ambiguity safeguard reduces the risk of destructive transfers but cannot prove that two records with the same name belong to the same person.

For production, use a globally unique, immutable member identifier. If that is unavailable, a trusted identity crosswalk and a governed process for resolving ambiguous matches are required before automatic country transfers can be considered safe.

## 4. Recency and latest-record selection

- Within a batch, duplicate member records are resolved deterministically using Enrollment Date, Flight Date, and source row number as tie-breakers.
- Across batches, `ingestion_batches.received_at` is used to prevent an older received batch from overwriting a newer assignment. `batch_id` provides an additional tie-breaker.
- Batch receipt time is a processing-time proxy; it does not prove when the member information actually changed.
- The supplied source files do not contain a reliable source-system update timestamp or version sequence.

A production implementation should use a source update timestamp, version number, or change sequence to determine the authoritative latest record.

## 5. Redemption processing and record counts

- Each JSON feed object is preserved in `raw_redemptions_json`.
- Valid redemption transactions are flattened into `fact_redemptions`.
- `txn_id` is unique in `fact_redemptions`.
- An exact replay of an existing transaction is treated as successfully processed without inserting a duplicate fact.
- Reuse of a transaction ID with different content is recorded as a conflict and rejected. Existing facts are not silently overwritten.
- Redemption batch counts use consistent units: total records equal processed transaction candidates plus rejected transaction/feed entries. Exact existing transaction replays count as processed.
- Newly inserted facts carry the current `ingestion_batch_id`. Historical records created before batch lineage was introduced may have a NULL batch ID.

The supplied sample redemption member ID (`223457`) does not match the supplied profile IDs. Therefore, a verified join between the sample redemption transactions and member profiles cannot be demonstrated using the provided data.

## 6. Tables

All tables are under the `skypoints` schema.

| Table | Purpose |
|---|---|
| `ingestion_batches` | Batch identity, checksum, lifecycle status, timestamps, and record counts |
| `raw_member_profiles` | Original profile rows with batch lineage |
| `stg_member_profiles` | Standardized accepted profile rows with batch lineage |
| `table_usa` | Published USA member profiles |
| `table_ind` | Published India member profiles |
| `table_aus` | Published Australia member profiles |
| `table_phil` | Published Philippines member profiles |
| `table_can` | Published Canada member profiles |
| `raw_redemptions_json` | Original redemption JSON objects with batch lineage |
| `fact_redemptions` | Flattened redemption transactions with batch lineage |
| `removed_records` | Rejected profile rows and rejection reasons |
| `data_quality_issues` | Non-blocking profile warnings, including identity ambiguities |
| `redemption_issues` | Rejected or conflicting redemption feed and transaction issues |

## 7. Project structure

```text
skypoints-loyalty-pipeline/
├── main.py
├── src/
│   ├── __init__.py
│   └── utils.py
├── sql/
│   └── 01_ddl_tables.sql
├── tests/
│   └── test_pipeline.py
├── data/
│   ├── USA(in).csv
│   ├── IND(in).csv
│   ├── AUS.xlsx
│   └── redemptions_sample.json
├── requirements.txt
└── README.md
```

## 8. Setup

### Prerequisites

- Python 3.10+
- PostgreSQL
- Required Python packages listed in `requirements.txt`

### Create and activate a virtual environment

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configure the database

The default local connection uses the current Mac username:

```text
postgresql+psycopg2://<your-mac-user>@localhost:5432/skypoints_db
```

Override the connection only if required:

```bash
export DATABASE_URL='postgresql+psycopg2://USER:PASSWORD@localhost:5432/skypoints_db'
```

### Apply the schema

Apply the DDL once, if it has not already been applied:

```bash
psql -d skypoints_db -v ON_ERROR_STOP=1 -f sql/01_ddl_tables.sql
```

The DDL is designed to be additive and does not drop or truncate existing tables. Back up an existing database before applying schema changes.

Do not run the experimental `02_global_member_identity.sql` migration. This implementation uses the assessment-level normalized `Member Name` identity approach and does not require a global `Member ID` registry.

### Run tests and pipeline

```bash
python -m pytest -v
python main.py
```

Set `DATA_DIR` to change the profile input directory, or `REDEMPTION_FILE` to select another redemption JSON file.

## 9. Tests

The automated unit tests cover:

- Date normalization across supported input formats.
- Age calculation and stale-member threshold logic.
- Mandatory and optional profile-field validation.
- Redemption JSON validation and flattening.
- Deterministic, content-sensitive batch-key generation.
- Redemption insertion, exact duplicate handling, and conflicting transaction IDs.
- Consistent redemption batch-count calculation.
- Latest profile selection and country-transfer safeguards.
- Ambiguous identity handling and protection against older batches overwriting newer assignments.

The test suite uses mocked database connections for persistence-path unit tests. It is not a substitute for PostgreSQL integration tests.

## 10. Validation results and limitations

The local assessment validation observed:

- 27 automated tests passed.
- Four ingestion batches completed successfully.
- Eight published member profiles across USA, India, and Australia.
- Two flattened redemption transactions.
- An invalid enrollment date was rejected and retained in the rejection audit table.
- A duplicate normalized name (`Mike`) was found across USA and Australia. This is treated as an identity ambiguity, not proof that both records belong to the same person.
- The supplied redemption member ID did not match the supplied profile IDs, preventing a verified member-profile join.
- Historical records may have NULL batch lineage because they were created before batch tracking was introduced.

These are observations from the local assessment data and database state, not guaranteed results for every run.

The tests are unit tests, not a complete PostgreSQL integration or performance test. No billion-record benchmark, streaming test, concurrency benchmark, or production cloud deployment has been performed.

## 11. Operational behaviour and scaling considerations

- Normal runs do not truncate historical raw, staging, rejection, issue, or target data.
- A batch's `SUCCEEDED` status is committed atomically with its database writes.
- The implementation reads profile files into pandas memory and uses PostgreSQL inserts/upserts. It is intended for a small-data assessment, not evidence of very-high-volume throughput.
- If a process is forcibly terminated while a batch is `PROCESSING`, inspect that batch before retrying. The implementation does not automatically assume that an active batch is abandoned.
- The implementation does not include a distributed scheduler or streaming platform.

For production-scale workloads, the architecture could be extended with:

- Durable object storage for source files and replay.
- Bulk database loading, such as PostgreSQL `COPY`.
- Partitioning and indexing based on workload patterns.
- Distributed processing where justified by volume.
- Monitoring, alerting, and data-quality observability.
- Deployment-level concurrency controls and recovery procedures.
- Source-provided immutable member identifiers and update/version metadata.

The current implementation is a batch-oriented reference solution demonstrating ingestion, validation, auditability, replay handling, transformation, and country-specific publishing for the supplied assessment data.