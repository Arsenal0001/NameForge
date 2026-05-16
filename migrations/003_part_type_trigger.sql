-- Add exact part_type → template mapping (applied programmatically in src/db.py run_migrations).
ALTER TABLE templates
ADD COLUMN part_type_trigger TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_templates_part_type
    ON templates (part_type_trigger)
    WHERE part_type_trigger IS NOT NULL;
