-- SkyPoints PostgreSQL reference schema.
-- Assessment key: Member Name. Member ID is NOT declared unique by the assessment.
CREATE SCHEMA IF NOT EXISTS skypoints;

DROP TABLE IF EXISTS skypoints.redemption_issues CASCADE;
DROP TABLE IF EXISTS skypoints.data_quality_issues CASCADE;
DROP TABLE IF EXISTS skypoints.fact_redemptions CASCADE;
DROP TABLE IF EXISTS skypoints.raw_redemptions_json CASCADE;
DROP TABLE IF EXISTS skypoints.table_phil CASCADE;
DROP TABLE IF EXISTS skypoints.table_can CASCADE;
DROP TABLE IF EXISTS skypoints.table_usa CASCADE;
DROP TABLE IF EXISTS skypoints.table_ind CASCADE;
DROP TABLE IF EXISTS skypoints.table_aus CASCADE;
DROP TABLE IF EXISTS skypoints.removed_records CASCADE;
DROP TABLE IF EXISTS skypoints.stg_member_profiles CASCADE;
DROP TABLE IF EXISTS skypoints.raw_member_profiles CASCADE;

CREATE TABLE skypoints.raw_member_profiles (
    raw_id BIGSERIAL PRIMARY KEY,
    source_file VARCHAR(255) NOT NULL,
    source_country VARCHAR(5) NOT NULL,
    source_row_number BIGINT NOT NULL,
    raw_record JSONB NOT NULL,
    ingested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Source values are preserved in *_raw columns; parsed fields follow dictionary types/lengths.
CREATE TABLE skypoints.stg_member_profiles (
    staging_id BIGSERIAL PRIMARY KEY,
    source_file VARCHAR(255) NOT NULL,
    source_country VARCHAR(5) NOT NULL,
    source_row_number BIGINT NOT NULL,
    member_name VARCHAR(255) NOT NULL,
    member_id VARCHAR(18) NOT NULL,
    enrollment_date DATE NOT NULL,
    flight_date DATE,
    tier_code CHAR(5),
    agent_name CHAR(255),
    state CHAR(5),
    country CHAR(5),
    post_code INTEGER,
    dob DATE,
    is_active CHAR(1),
    individual_or_corporate VARCHAR(20), -- present in one supplied source, absent from assessment dictionary
    dob_raw VARCHAR(50),
    enrollment_date_raw VARCHAR(50),
    flight_date_raw VARCHAR(50),
    age INTEGER,
    is_stale_member CHAR(1),
    ingested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_stg_member_name_norm ON skypoints.stg_member_profiles (LOWER(BTRIM(member_name)));
CREATE INDEX idx_stg_member_id ON skypoints.stg_member_profiles (member_id);

-- Country tables use Member Name as the assessment-defined key.
CREATE TABLE skypoints.table_usa (
    member_name VARCHAR(255) PRIMARY KEY,
    member_id VARCHAR(18) NOT NULL,
    enrollment_date DATE NOT NULL,
    flight_date DATE,
    tier_code CHAR(5),
    agent_name CHAR(255),
    state CHAR(5),
    country CHAR(5),
    post_code INTEGER,
    dob DATE,
    is_active CHAR(1),
    individual_or_corporate VARCHAR(20),
    age INTEGER,
    is_stale_member CHAR(1),
    source_file VARCHAR(255),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE skypoints.table_ind (LIKE skypoints.table_usa INCLUDING ALL);
CREATE TABLE skypoints.table_aus (LIKE skypoints.table_usa INCLUDING ALL);
CREATE TABLE skypoints.table_phil (LIKE skypoints.table_usa INCLUDING ALL);
CREATE TABLE skypoints.table_can (LIKE skypoints.table_usa INCLUDING ALL);

-- Enforce the assessment key after trimming and case normalization as well.
CREATE UNIQUE INDEX uq_table_usa_member_name_norm ON skypoints.table_usa (LOWER(BTRIM(member_name)));
CREATE UNIQUE INDEX uq_table_ind_member_name_norm ON skypoints.table_ind (LOWER(BTRIM(member_name)));
CREATE UNIQUE INDEX uq_table_aus_member_name_norm ON skypoints.table_aus (LOWER(BTRIM(member_name)));
CREATE UNIQUE INDEX uq_table_phil_member_name_norm ON skypoints.table_phil (LOWER(BTRIM(member_name)));
CREATE UNIQUE INDEX uq_table_can_member_name_norm ON skypoints.table_can (LOWER(BTRIM(member_name)));

CREATE TABLE skypoints.raw_redemptions_json (
    batch_id BIGSERIAL PRIMARY KEY,
    source_file VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    payload_hash CHAR(64) NOT NULL UNIQUE,
    received_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE skypoints.fact_redemptions (
    txn_id VARCHAR(50) PRIMARY KEY,
    member_id VARCHAR(18) NOT NULL,
    txn_date DATE NOT NULL,
    partner VARCHAR(100) NOT NULL,
    miles_redeemed BIGINT NOT NULL CHECK (miles_redeemed >= 0),
    status VARCHAR(30) NOT NULL,
    feed_date DATE NOT NULL,
    ingested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_redemptions_member_id ON skypoints.fact_redemptions(member_id);
CREATE INDEX idx_redemptions_txn_date ON skypoints.fact_redemptions(txn_date);

CREATE TABLE skypoints.removed_records (
    removal_id BIGSERIAL PRIMARY KEY,
    source_file VARCHAR(255) NOT NULL,
    source_country VARCHAR(5) NOT NULL,
    source_row_number BIGINT NOT NULL,
    raw_record JSONB NOT NULL,
    rejection_reason TEXT NOT NULL,
    removed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE skypoints.data_quality_issues (
    issue_id BIGSERIAL PRIMARY KEY,
    source_file VARCHAR(255) NOT NULL,
    source_country CHAR(5),
    source_row_number BIGINT,
    issue_type VARCHAR(30) NOT NULL,
    issue_detail TEXT NOT NULL,
    recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE skypoints.redemption_issues (
    issue_id BIGSERIAL PRIMARY KEY,
    source_file VARCHAR(255) NOT NULL,
    source_row_number BIGINT,
    issue_type VARCHAR(40) NOT NULL,
    issue_detail TEXT NOT NULL,
    recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
