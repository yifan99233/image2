-- Run only after private row backups, verified ADX2 routes, maintenance and drain.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='20s';
SELECT id FROM image_models WHERE site_id=1 AND id IN(215,216,217,266,267) FOR UPDATE;
DO $$ BEGIN
 IF (SELECT count(*) FROM image_models WHERE site_id=1 AND provider_id=279 AND
   (id=215 AND vendor_model='gpt-image-2-adx1' OR id=216 AND vendor_model='gpt-image-2.5-flare-adx1' OR id=217 AND vendor_model='gpt-image-2.5-sunburst-adx1' OR id=266 AND vendor_model='nano-banana-2-adx1' OR id=267 AND vendor_model='nano-banana-2.1-adx1'))<>5 THEN RAISE EXCEPTION 'Unexpected Magic model identities';END IF;
 IF NOT EXISTS(SELECT 1 FROM image_model_providers WHERE id=279 AND site_id=1 AND base_url='https://agent.shyfai.com/v1' AND is_active) THEN RAISE EXCEPTION 'Unexpected NewAPI provider';END IF;
END $$;
UPDATE image_models SET vendor_model=replace(vendor_model,'-adx1','-adx2'),
 name=replace(name,'(ADX1)','(ADX2)'),max_input_images=CASE WHEN id=267 THEN 14 ELSE 6 END,
 updated_at=now() WHERE site_id=1 AND id IN(215,216,266,267);
-- FF has no Sunburst implementation; preserve history, stop offering the model.
UPDATE image_models SET is_active=false,updated_at=now() WHERE site_id=1 AND id=217;
-- Firefly Banana 2 supports the standard ratios; extreme ratios belong to 2.1.
DELETE FROM image_model_aspect_ratios mr USING image_aspect_ratio_specs r
 WHERE mr.aspect_ratio_id=r.id AND mr.model_id=266 AND r.code IN('1:4','4:1','1:8','8:1');
-- Explicit GPT resolution tiers require an explicit ratio in the Firefly API.
DELETE FROM image_model_aspect_ratios mr USING image_aspect_ratio_specs r
 WHERE mr.aspect_ratio_id=r.id AND mr.model_id IN(215,216) AND r.code='auto';
-- Prices and existing model IDs are deliberately retained, including 2K/4K.
COMMIT;
