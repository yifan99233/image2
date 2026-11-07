"""Seven-day generated-image retention with reference fencing."""
from alembic import op
import sqlalchemy as sa

revision = "20261019_0100"
down_revision = "20261012_0100"
branch_labels = None
depends_on = None

# Readers that create references take KEY SHARE on the asset. The cleaner takes
# FOR UPDATE before its final reference scan and tombstone commit. Thus a new
# reference either commits before that scan or observes the tombstone and fails.
GUARD = r"""
CREATE OR REPLACE FUNCTION image_retention_reference_guard() RETURNS trigger AS $$
DECLARE payload text; item record; filenames text[];
BEGIN
  IF TG_TABLE_NAME = 'image_tasks' THEN
    payload := concat_ws(' ', NEW.input_image_url, NEW.input_image_urls);
    IF NEW.is_collected OR NEW.is_gallery_featured THEN
      payload := payload || ' ' || coalesce(NEW.output_image_url, '') || ' ' || coalesce(NEW.output_image_r2_url, '');
    END IF;
  ELSIF TG_TABLE_NAME = 'user_material_assets' THEN
    SELECT retention_pending_at INTO item FROM image_assets WHERE id=NEW.image_asset_id FOR KEY SHARE;
    IF item.retention_pending_at IS NOT NULL THEN
      RAISE EXCEPTION 'Image has expired' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  ELSE
    payload := to_jsonb(NEW)::text;
  END IF;
  SELECT array_agg(m[1]) INTO filenames FROM regexp_matches(payload, '([a-f0-9]{32}\.[a-zA-Z0-9]+)', 'g') m;
  IF filenames IS NULL THEN RETURN NEW; END IF;
  FOR item IN SELECT id, retention_pending_at FROM image_assets
    WHERE regexp_replace(storage_key, '^.*/', '') = ANY(filenames)
    ORDER BY id FOR KEY SHARE
  LOOP
    IF item.retention_pending_at IS NOT NULL THEN
      RAISE EXCEPTION 'Image has expired' USING ERRCODE='23514';
    END IF;
  END LOOP;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

TABLES = ('image_tasks', 'user_material_assets', 'canvas_projects', 'material_assets', 'site_configs')

def upgrade():
    op.add_column('image_assets', sa.Column('retention_pending_at', sa.DateTime(timezone=True)))
    op.add_column('image_assets', sa.Column('storage_deleted_at', sa.DateTime(timezone=True)))
    op.add_column('image_assets', sa.Column('retention_error', sa.String(128)))
    op.add_column('image_tasks', sa.Column('output_expired_at', sa.DateTime(timezone=True)))
    op.execute("CREATE INDEX ix_image_assets_retention ON image_assets (id) WHERE source='generated' AND storage_deleted_at IS NULL")
    op.execute("CREATE INDEX ix_image_assets_filename ON image_assets (regexp_replace(storage_key, '^.*/', ''))")
    op.create_index('ix_image_tasks_output_url', 'image_tasks', ['output_image_url'])
    op.execute(GUARD)
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in TABLES:
        if table in existing:
            op.execute(f'CREATE TRIGGER image_retention_guard BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION image_retention_reference_guard()')


def downgrade():
    # Losing tombstones would make deleted results appear downloadable again.
    if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM image_assets WHERE retention_pending_at IS NOT NULL)')).scalar():
        raise RuntimeError('Retention has run; keep tombstones when rolling back application code')
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in TABLES:
        if table in existing:
            op.execute(f'DROP TRIGGER IF EXISTS image_retention_guard ON {table}')
    op.execute('DROP FUNCTION image_retention_reference_guard()')
    op.drop_index('ix_image_tasks_output_url', table_name='image_tasks')
    op.drop_index('ix_image_assets_filename', table_name='image_assets')
    op.drop_index('ix_image_assets_retention', table_name='image_assets')
    op.drop_column('image_tasks', 'output_expired_at')
    for col in ('retention_error', 'storage_deleted_at', 'retention_pending_at'):
        op.drop_column('image_assets', col)
