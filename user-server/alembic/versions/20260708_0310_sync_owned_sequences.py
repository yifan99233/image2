"""sync owned sequences with existing data

Revision ID: 20260708_0310
Revises: 20260708_0300
Create Date: 2026-07-08 19:58:00
"""

from alembic import op


revision = "20260708_0310"
down_revision = "20260708_0300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            sequence_record record;
            max_id bigint;
        BEGIN
            FOR sequence_record IN
                SELECT
                    table_schema,
                    table_name,
                    column_name,
                    pg_get_serial_sequence(format('%I.%I', table_schema, table_name), column_name) AS sequence_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND column_name = 'id'
            LOOP
                IF sequence_record.sequence_name IS NULL THEN
                    CONTINUE;
                END IF;

                EXECUTE format(
                    'SELECT COALESCE(MAX(%I), 0) FROM %I.%I',
                    sequence_record.column_name,
                    sequence_record.table_schema,
                    sequence_record.table_name
                )
                INTO max_id;

                IF max_id > 0 THEN
                    PERFORM setval(sequence_record.sequence_name::regclass, max_id, true);
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    pass
