-- SkyPoints Data Engineering Assessment
-- NOTE: member_id is used as the operational primary key for routing and joins.
-- The assessment data dictionary marks Member Name as a key;
-- but names are not reliable identifiers.

CREATE SCHEMA IF NOT EXISTS skypoints;

DROP TABLE IF EXISTS skypoints.table_phil CASCADE;
DROP TABLE IF EXISTS skypoints.table_can CASCADE;
DROP TABLE IF EXISTS skypoints.table_usa CASCADE;
DROP TABLE IF EXISTS skypoints.table_ind CASCADE;
DROP TABLE IF EXISTS skypoints.table_aus CASCADE;
DROP TABLE IF EXISTS skypoints.fact_redemptions CASCADE;
DROP TABLE IF EXISTS skypoints.raw_redemptions_json CASCADE;
DROP TABLE IF EXISTS skypoints.removed_records CASCADE;
DROP TABLE IF EXISTS skypoints.stg_member_profiles CASCADE;
DROP TABLE IF EXISTS skypoints.raw_member_profiles CASCADE;

-- 1. Raw member landing table: preserve source values before transformation.
CREATE TABLE skypoints.raw_member_profiles (
    raw_id BIGSERIAL PRIMARY KEY,
    source_file VARCHAR(255) NOT NULL,
    source_country VARCHAR(10) NOT NULL,
    source_row_number BIGINT NOT NULL,
    raw_record JSONB NOT NULL,
    ingested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Staging: raw date strings are retained alongside parsed DATE values.
CREATE TABLE skypoints.stg_member_profiles (
    staging_id BIGSERIAL PRIMARY KEY,
    source_file VARCHAR(255) NOT NULL,
    source_country VARCHAR(10) NOT NULL,
    source_row_number BIGINT NOT NULL,
    member_id VARCHAR(50) NOT NULL,
    member_name VARCHAR(255) NOT NULL,
    tier_code VARCHAR(10),
    dob_raw VARCHAR(50),
    enrollment_date_raw VARCHAR(50),
    flight_date_raw VARCHAR(50),
    dob DATE,
    enrollment_date DATE NOT NULL,
    flight_date DATE,
    agent_name VARCHAR(255),
    state VARCHAR(10),
    country VARCHAR(10),
    post_code INTEGER,
    is_active CHAR(1),
    individual_or_corporate VARCHAR(20),
    age INTEGER,
    is_stale_member CHAR(1),
    validation_status VARCHAR(20) NOT NULL DEFAULT 'VALID',
    ingested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_stg_member_id ON skypoints.stg_member_profiles(member_id);
CREATE INDEX idx_stg_source_country ON skypoints.stg_member_profiles(source_country);

-- 3. Country target tables share an identical structure.
-- member_id is the primary key so a member is not duplicated within a country.
CREATE TABLE skypoints.table_usa (
    member_id VARCHAR(50) PRIMARY KEY,
    member_name VARCHAR(255) NOT NULL,
    tier_code VARCHAR(10),
    enrollment_date DATE NOT NULL,
    flight_date DATE,
    dob DATE,
    agent_name VARCHAR(255),
    state VARCHAR(10),
    country VARCHAR(10),
    post_code INTEGER,
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

-- 4. Raw JSON landing and flattened redemption fact table.
CREATE TABLE skypoints.raw_redemptions_json (
    batch_id BIGSERIAL PRIMARY KEY,
    payload JSONB NOT NULL,
    received_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE skypoints.fact_redemptions (
    txn_id VARCHAR(50) PRIMARY KEY,
    member_id VARCHAR(50) NOT NULL,
    txn_date DATE NOT NULL,
    partner VARCHAR(100),
    miles_redeemed BIGINT,
    status VARCHAR(30),
    feed_date DATE,
    ingested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_redemptions_member
    ON skypoints.fact_redemptions(member_id);

-- 5. Rejected records: retain the source location and original values.
CREATE TABLE skypoints.removed_records (
    removal_id BIGSERIAL PRIMARY KEY,
    source_file VARCHAR(255) NOT NULL,
    source_country VARCHAR(10) NOT NULL,
    source_row_number BIGINT NOT NULL,
    raw_record JSONB NOT NULL,
    rejection_reason TEXT NOT NULL,
    removed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
