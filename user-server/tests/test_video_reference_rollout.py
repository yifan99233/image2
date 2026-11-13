"""Run against an isolated TEST_DATABASE_URL; all fixture tables are TEMP."""
import os
from pathlib import Path

import asyncpg


async def test_magic_reference_rollout_preserves_prices_scope_and_is_idempotent():
    db = await asyncpg.connect(os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg:", "postgresql:"))
    try:
        await db.execute("""
          CREATE TEMP TABLE image_models(id bigint, site_id bigint, vendor_model text, work_type text,
            max_input_images int DEFAULT 0, description text DEFAULT '', is_active bool DEFAULT true,
            is_public bool DEFAULT true, capability_type text DEFAULT 'video');
          CREATE TEMP TABLE image_model_prices(id bigint GENERATED ALWAYS AS IDENTITY, site_id bigint,
            model_id bigint, work_type text, resolution text DEFAULT '720p', aspect_ratio text DEFAULT '4',
            output_count int DEFAULT 1, quality text DEFAULT 'any', credit_cost int DEFAULT 0,
            fixed_surcharge numeric DEFAULT 30, version int DEFAULT 1,
            effective_at timestamptz DEFAULT now(), is_active bool DEFAULT true, change_reason text DEFAULT 'fixture');
          INSERT INTO image_models(id,site_id,vendor_model,work_type) VALUES
            (1,1,'firefly-veo31-lite','text_to_video'), (2,1,'firefly-omniflash','text_to_video'),
            (3,1,'muse-video','text_to_video,image_to_video'), (4,2,'firefly-veo31-lite','text_to_video'),
            (5,1,'firefly-veo31-fast','text_to_video'), (6,1,'firefly-omniflash','text_to_video');
          UPDATE image_models SET is_active=false WHERE id=6;
          INSERT INTO image_model_prices(site_id,model_id,work_type)
            SELECT site_id,id,'text_to_video' FROM image_models;
          INSERT INTO image_model_prices(site_id,model_id,work_type,fixed_surcharge)
            VALUES(1,3,'image_to_video',19);
        """)
        script = Path(__file__).resolve().parents[2] / "scripts/unified-video-references.sql"
        sql = "\n".join(line for line in script.read_text().splitlines() if not line.startswith("\\"))
        await db.execute(sql)
        first = await db.fetch("SELECT * FROM image_model_prices ORDER BY id")
        await db.execute(sql)
        assert first == await db.fetch("SELECT * FROM image_model_prices ORDER BY id")
        assert await db.fetchval("SELECT fixed_surcharge FROM image_model_prices WHERE model_id=3 AND work_type='image_to_video'") == 19
        assert await db.fetchval("SELECT fixed_surcharge FROM image_model_prices WHERE model_id=1 AND work_type='image_to_video'") == 30
        rows = await db.fetch("SELECT id,work_type,max_input_images FROM image_models ORDER BY id")
        assert [(r["work_type"], r["max_input_images"]) for r in rows[:3]] == [("text_to_video,image_to_video", 2), ("text_to_video,image_to_video", 10), ("text_to_video,image_to_video", 4)]
        assert all(r["work_type"] == "text_to_video" and r["max_input_images"] == 0 for r in rows[3:])
        assert await db.fetchval("SELECT count(*) FROM image_model_prices WHERE model_id IN (4,5,6) AND work_type='image_to_video'") == 0
    finally:
        await db.close()
