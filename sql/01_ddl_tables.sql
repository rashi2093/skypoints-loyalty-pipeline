-- Safe, additive schema setup. This script never drops or truncates data.
CREATE SCHEMA IF NOT EXISTS skypoints;

CREATE TABLE IF NOT EXISTS skypoints.ingestion_batches (
    batch_id BIGSERIAL PRIMARY KEY,
    batch_key CHAR(64) NOT NULL UNIQUE,
    feed_type VARCHAR(30) NOT NULL,
    source_file VARCHAR(255) NOT NULL,
    checksum CHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('RECEIVED','PROCESSING','SUCCEEDED','FAILED')),
    received_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    total_records BIGINT NOT NULL DEFAULT 0,
    processed_records BIGINT NOT NULL DEFAULT 0,
    rejected_records BIGINT NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS skypoints.raw_member_profiles (
    raw_id BIGSERIAL PRIMARY KEY, source_file VARCHAR(255) NOT NULL,
    source_country VARCHAR(5) NOT NULL, source_row_number BIGINT NOT NULL,
    raw_record JSONB NOT NULL, ingested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE skypoints.raw_member_profiles
    ADD COLUMN IF NOT EXISTS ingestion_batch_id BIGINT REFERENCES skypoints.ingestion_batches(batch_id);

CREATE TABLE IF NOT EXISTS skypoints.stg_member_profiles (
    staging_id BIGSERIAL PRIMARY KEY, source_file VARCHAR(255) NOT NULL,
    source_country VARCHAR(5) NOT NULL, source_row_number BIGINT NOT NULL,
    member_name VARCHAR(255) NOT NULL, member_id VARCHAR(18) NOT NULL,
    enrollment_date DATE NOT NULL, flight_date DATE, tier_code CHAR(5),
    agent_name CHAR(255), state CHAR(5), country CHAR(5), post_code INTEGER,
    dob DATE, is_active CHAR(1), individual_or_corporate VARCHAR(20),
    dob_raw VARCHAR(50), enrollment_date_raw VARCHAR(50), flight_date_raw VARCHAR(50),
    age INTEGER, is_stale_member CHAR(1), ingested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE skypoints.stg_member_profiles
    ADD COLUMN IF NOT EXISTS ingestion_batch_id BIGINT REFERENCES skypoints.ingestion_batches(batch_id);
CREATE INDEX IF NOT EXISTS idx_stg_member_name_norm ON skypoints.stg_member_profiles (LOWER(BTRIM(member_name)));
CREATE INDEX IF NOT EXISTS idx_stg_member_id ON skypoints.stg_member_profiles (member_id);
CREATE INDEX IF NOT EXISTS idx_stg_batch ON skypoints.stg_member_profiles (ingestion_batch_id);

-- Existing assessment target key is retained. Do not run destructive rebuilds.
CREATE TABLE IF NOT EXISTS skypoints.table_usa (
    member_name VARCHAR(255) PRIMARY KEY, member_id VARCHAR(18) NOT NULL,
    enrollment_date DATE NOT NULL, flight_date DATE, tier_code CHAR(5),
    agent_name CHAR(255), state CHAR(5), country CHAR(5), post_code INTEGER,
    dob DATE, is_active CHAR(1), individual_or_corporate VARCHAR(20),
    age INTEGER, is_stale_member CHAR(1), source_file VARCHAR(255),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS skypoints.table_ind (LIKE skypoints.table_usa INCLUDING ALL);
CREATE TABLE IF NOT EXISTS skypoints.table_aus (LIKE skypoints.table_usa INCLUDING ALL);
CREATE TABLE IF NOT EXISTS skypoints.table_phil (LIKE skypoints.table_usa INCLUDING ALL);
CREATE TABLE IF NOT EXISTS skypoints.table_can (LIKE skypoints.table_usa INCLUDING ALL);
CREATE UNIQUE INDEX IF NOT EXISTS uq_table_usa_member_name_norm ON skypoints.table_usa (LOWER(BTRIM(member_name)));
CREATE UNIQUE INDEX IF NOT EXISTS uq_table_ind_member_name_norm ON skypoints.table_ind (LOWER(BTRIM(member_name)));
CREATE UNIQUE INDEX IF NOT EXISTS uq_table_aus_member_name_norm ON skypoints.table_aus (LOWER(BTRIM(member_name)));
CREATE UNIQUE INDEX IF NOT EXISTS uq_table_phil_member_name_norm ON skypoints.table_phil (LOWER(BTRIM(member_name)));
CREATE UNIQUE INDEX IF NOT EXISTS uq_table_can_member_name_norm ON skypoints.table_can (LOWER(BTRIM(member_name)));

CREATE TABLE IF NOT EXISTS skypoints.raw_redemptions_json (
    batch_id BIGSERIAL PRIMARY KEY, source_file VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL, payload_hash CHAR(64) NOT NULL,
    received_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE skypoints.raw_redemptions_json
    ADD COLUMN IF NOT EXISTS ingestion_batch_id BIGINT REFERENCES skypoints.ingestion_batches(batch_id);
-- The previous version enforced a global payload hash. Scope it to each input batch.
ALTER TABLE skypoints.raw_redemptions_json
    DROP CONSTRAINT IF EXISTS raw_redemptions_json_payload_hash_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_redemption_batch_hash
    ON skypoints.raw_redemptions_json (ingestion_batch_id,payload_hash);

CREATE TABLE IF NOT EXISTS skypoints.fact_redemptions (
    txn_id VARCHAR(50) PRIMARY KEY, member_id VARCHAR(18) NOT NULL,
    txn_date DATE NOT NULL, partner VARCHAR(100) NOT NULL,
    miles_redeemed BIGINT NOT NULL CHECK (miles_redeemed >= 0),
    status VARCHAR(30) NOT NULL, feed_date DATE NOT NULL,
    ingested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE skypoints.fact_redemptions
    ADD COLUMN IF NOT EXISTS ingestion_batch_id BIGINT REFERENCES skypoints.ingestion_batches(batch_id);
CREATE INDEX IF NOT EXISTS idx_redemptions_member_id ON skypoints.fact_redemptions(member_id);
CREATE INDEX IF NOT EXISTS idx_redemptions_txn_date ON skypoints.fact_redemptions(txn_date);
CREATE INDEX IF NOT EXISTS idx_redemptions_batch ON skypoints.fact_redemptions(ingestion_batch_id);

CREATE TABLE IF NOT EXISTS skypoints.removed_records (
    removal_id BIGSERIAL PRIMARY KEY, source_file VARCHAR(255) NOT NULL,
    source_country VARCHAR(5) NOT NULL, source_row_number BIGINT NOT NULL,
    raw_record JSONB NOT NULL, rejection_reason TEXT NOT NULL,
    removed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE skypoints.removed_records
    ADD COLUMN IF NOT EXISTS ingestion_batch_id BIGINT REFERENCES skypoints.ingestion_batches(batch_id);

CREATE TABLE IF NOT EXISTS skypoints.data_quality_issues (
    issue_id BIGSERIAL PRIMARY KEY, source_file VARCHAR(255) NOT NULL,
    source_country CHAR(5), source_row_number BIGINT, issue_type VARCHAR(30) NOT NULL,
    issue_detail TEXT NOT NULL, recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE skypoints.data_quality_issues
    ADD COLUMN IF NOT EXISTS ingestion_batch_id BIGINT REFERENCES skypoints.ingestion_batches(batch_id);

CREATE TABLE IF NOT EXISTS skypoints.redemption_issues (
    issue_id BIGSERIAL PRIMARY KEY, source_file VARCHAR(255) NOT NULL,
    source_row_number BIGINT, issue_type VARCHAR(40) NOT NULL,
    issue_detail TEXT NOT NULL, recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE skypoints.redemption_issues
    ADD COLUMN IF NOT EXISTS ingestion_batch_id BIGINT REFERENCES skypoints.ingestion_batches(batch_id);
