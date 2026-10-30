-- Schema setup
CREATE SCHEMA IF NOT EXISTS skypoints;
SET search_path TO skypoints, public;

-- Drop existing tables to allow fresh rebuilds
DROP TABLE IF EXISTS table_usa CASCADE;
DROP TABLE IF EXISTS table_ind CASCADE;
DROP TABLE IF EXISTS table_aus CASCADE;
DROP TABLE IF EXISTS fact_redemptions CASCADE;
DROP TABLE IF EXISTS stg_member_profiles CASCADE;
DROP TABLE IF EXISTS removed_records CASCADE;
DROP TABLE IF EXISTS raw_redemptions_json CASCADE;

-- 1. Unified Staging Table (Cleaned data with derived business columns)
CREATE TABLE stg_member_profiles (
    staging_id SERIAL PRIMARY KEY,
    source_country VARCHAR(10) NOT NULL,
    member_id VARCHAR(50) NOT NULL,
    member_name VARCHAR(255) NOT NULL,
    dob DATE,
    tier_code VARCHAR(10),
    enrollment_date DATE,
    flight_date DATE,
    individual_or_corporate VARCHAR(20) DEFAULT 'I',
    age INT,
    is_stale_member CHAR(1) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Target Country Tables (One per country, member_name is the business key)
-- Ideally member_id must be the key - when we have millions of records. 
CREATE TABLE table_usa (
    member_id VARCHAR(50),
    member_name VARCHAR(255) PRIMARY KEY,
    tier_code VARCHAR(10),
    enrollment_date DATE,
    flight_date DATE,
    dob DATE,
    age INT,
    is_stale_member CHAR(1),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE table_ind (
    member_id VARCHAR(50),
    member_name VARCHAR(255) PRIMARY KEY,
    tier_code VARCHAR(10),
    enrollment_date DATE,
    flight_date DATE,
    dob DATE,
    age INT,
    individual_or_corporate VARCHAR(20),
    is_stale_member CHAR(1),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE table_aus (
    member_id VARCHAR(50),
    member_name VARCHAR(255) PRIMARY KEY,
    tier_code VARCHAR(10),
    enrollment_date DATE,
    flight_date DATE,
    dob DATE,
    age INT,
    is_stale_member CHAR(1),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Redemptions JSON & Flattened Fact Table
CREATE TABLE raw_redemptions_json (
    batch_id SERIAL PRIMARY KEY,
    payload JSONB NOT NULL,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE fact_redemptions (
    txn_id VARCHAR(50) PRIMARY KEY,
    member_id VARCHAR(50) NOT NULL,
    txn_date DATE NOT NULL,
    partner VARCHAR(100),
    miles_redeemed INT,
    status VARCHAR(20),
    feed_date DATE,
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_redemptions_member ON fact_redemptions(member_id);

-- 4. Removed Table (For rows with invalid data)
CREATE TABLE removed_records (
    quarantine_id SERIAL PRIMARY KEY,
    source_country VARCHAR(10),
    raw_record JSONB,
    rejection_reason TEXT,
    quarantined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);