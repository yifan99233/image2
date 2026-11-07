"""Allow task metadata updates without weakening new-reference protection."""
from alembic import op

revision = "20261106_0100"
down_revision = "20261102_0100"
branch_labels = None
depends_on = None

METADATA_ONLY_GUARD = """    -- Metadata-only updates do not add references. Old input objects may have
    -- expired already; revalidating them here would prevent recording output
    -- expiration and roll back the entire retention batch.
    IF TG_OP = 'UPDATE' THEN
      IF NEW.input_image_url IS NOT DISTINCT FROM OLD.input_image_url
         AND NEW.input_image_urls IS NOT DISTINCT FROM OLD.input_image_urls
         AND NEW.is_collected IS NOT DISTINCT FROM OLD.is_collected
         AND NEW.is_gallery_featured IS NOT DISTINCT FROM OLD.is_gallery_featured
         AND NEW.output_image_url IS NOT DISTINCT FROM OLD.output_image_url
         AND NEW.output_image_r2_url IS NOT DISTINCT FROM OLD.output_image_r2_url
         AND to_jsonb(NEW)->'output_image_assets' IS NOT DISTINCT FROM to_jsonb(OLD)->'output_image_assets'
      THEN
        RETURN NEW;
      END IF;
    END IF;
"""

GUARD = r"""CREATE OR REPLACE FUNCTION image_retention_reference_guard() RETURNS trigger AS $$
DECLARE payload text; item record; filenames text[];
BEGIN
  IF TG_TABLE_NAME = 'image_tasks' THEN
    -- Metadata-only updates do not add references. Old input objects may have
    -- expired already; revalidating them here would prevent recording output
    -- expiration and roll back the entire retention batch.
    IF TG_OP = 'UPDATE' THEN
      IF NEW.input_image_url IS NOT DISTINCT FROM OLD.input_image_url
         AND NEW.input_image_urls IS NOT DISTINCT FROM OLD.input_image_urls
         AND NEW.is_collected IS NOT DISTINCT FROM OLD.is_collected
         AND NEW.is_gallery_featured IS NOT DISTINCT FROM OLD.is_gallery_featured
         AND NEW.output_image_url IS NOT DISTINCT FROM OLD.output_image_url
         AND NEW.output_image_r2_url IS NOT DISTINCT FROM OLD.output_image_r2_url
         AND to_jsonb(NEW)->'output_image_assets' IS NOT DISTINCT FROM to_jsonb(OLD)->'output_image_assets'
      THEN
        RETURN NEW;
      END IF;
    END IF;
    payload := concat_ws(' ', NEW.input_image_url, NEW.input_image_urls);
    IF NEW.is_collected OR NEW.is_gallery_featured THEN
      payload := payload || ' ' || coalesce(NEW.output_image_url, '') || ' ' || coalesce(NEW.output_image_r2_url, '') || ' ' || coalesce(to_jsonb(NEW)->>'output_image_assets', '');
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

def upgrade():
    op.execute(GUARD)

def downgrade():
    op.execute(GUARD.replace(METADATA_ONLY_GUARD, "", 1))
