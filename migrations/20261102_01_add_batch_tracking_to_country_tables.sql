BEGIN;

-- Add batch tracking columns to country-specific member tables.

ALTER TABLE skypoints.table_usa
    ADD COLUMN IF NOT EXISTS last_batch_received_at TIMESTAMP WITHOUT TIME ZONE,
    ADD COLUMN IF NOT EXISTS last_batch_id BIGINT;

ALTER TABLE skypoints.table_ind
    ADD COLUMN IF NOT EXISTS last_batch_received_at TIMESTAMP WITHOUT TIME ZONE,
    ADD COLUMN IF NOT EXISTS last_batch_id BIGINT;

ALTER TABLE skypoints.table_aus
    ADD COLUMN IF NOT EXISTS last_batch_received_at TIMESTAMP WITHOUT TIME ZONE,
    ADD COLUMN IF NOT EXISTS last_batch_id BIGINT;

ALTER TABLE skypoints.table_phil
    ADD COLUMN IF NOT EXISTS last_batch_received_at TIMESTAMP WITHOUT TIME ZONE,
    ADD COLUMN IF NOT EXISTS last_batch_id BIGINT;

ALTER TABLE skypoints.table_can
    ADD COLUMN IF NOT EXISTS last_batch_received_at TIMESTAMP WITHOUT TIME ZONE,
    ADD COLUMN IF NOT EXISTS last_batch_id BIGINT;

-- Add foreign key constraints if they do not already exist.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_table_usa_last_batch_id'
          AND conrelid = 'skypoints.table_usa'::regclass
    ) THEN
        ALTER TABLE skypoints.table_usa
        ADD CONSTRAINT fk_table_usa_last_batch_id
        FOREIGN KEY (last_batch_id)
        REFERENCES skypoints.ingestion_batches(batch_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_table_ind_last_batch_id'
          AND conrelid = 'skypoints.table_ind'::regclass
    ) THEN
        ALTER TABLE skypoints.table_ind
        ADD CONSTRAINT fk_table_ind_last_batch_id
        FOREIGN KEY (last_batch_id)
        REFERENCES skypoints.ingestion_batches(batch_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_table_aus_last_batch_id'
          AND conrelid = 'skypoints.table_aus'::regclass
    ) THEN
        ALTER TABLE skypoints.table_aus
        ADD CONSTRAINT fk_table_aus_last_batch_id
        FOREIGN KEY (last_batch_id)
        REFERENCES skypoints.ingestion_batches(batch_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_table_phil_last_batch_id'
          AND conrelid = 'skypoints.table_phil'::regclass
    ) THEN
        ALTER TABLE skypoints.table_phil
        ADD CONSTRAINT fk_table_phil_last_batch_id
        FOREIGN KEY (last_batch_id)
        REFERENCES skypoints.ingestion_batches(batch_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_table_can_last_batch_id'
          AND conrelid = 'skypoints.table_can'::regclass
    ) THEN
        ALTER TABLE skypoints.table_can
        ADD CONSTRAINT fk_table_can_last_batch_id
        FOREIGN KEY (last_batch_id)
        REFERENCES skypoints.ingestion_batches(batch_id);
    END IF;
END $$;

COMMIT;
