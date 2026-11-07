-- Apply once during the drained Magic maintenance deployment, after both migrations.
-- Existing prices remain as inactive history; accepted task snapshots are untouched.
BEGIN;
SET LOCAL lock_timeout = '10s';
SELECT id FROM image_models WHERE site_id=1 AND id IN (215,216) ORDER BY id FOR UPDATE;
SELECT id FROM image_model_prices WHERE site_id=1 AND model_id IN (215,216) ORDER BY id FOR UPDATE;
DO $$
BEGIN
  IF (SELECT count(*) FROM image_models WHERE site_id=1 AND provider_id=279
      AND ((id=215 AND vendor_model='gpt-image-2-adx2') OR (id=216 AND vendor_model='gpt-image-2.5-flare-adx2'))) != 2 THEN
    RAISE EXCEPTION 'ADX2 model identity changed; abort';
  END IF;
  IF (SELECT count(*) FROM image_model_prices WHERE site_id=1 AND model_id IN (215,216) AND is_active) != 108
     OR EXISTS (SELECT 1 FROM image_model_prices WHERE site_id=1 AND model_id IN (215,216) AND is_active
       AND (quality!='any' OR credit_cost!=2 OR fixed_surcharge!=0 OR output_count!=1
         OR resolution NOT IN ('1k','2k','4k') OR work_type NOT IN ('text_to_image','image_to_image'))) THEN
    RAISE EXCEPTION 'ADX2 current prices changed; abort';
  END IF;
END $$;
CREATE TEMP TABLE adx2_previous_prices ON COMMIT DROP AS
SELECT * FROM image_model_prices WHERE site_id=1 AND model_id IN (215,216) AND is_active;
UPDATE image_model_prices SET is_active=false, updated_at=now()
WHERE id IN (SELECT id FROM adx2_previous_prices);
INSERT INTO image_model_prices
(site_id,model_id,work_type,resolution,aspect_ratio,output_count,quality,credit_cost,fixed_surcharge,version,is_active,change_reason)
SELECT p.site_id,p.model_id,p.work_type,p.resolution,p.aspect_ratio,p.output_count,q.quality,q.cost,p.fixed_surcharge,
  1+COALESCE((SELECT max(old.version) FROM image_model_prices old WHERE old.site_id=p.site_id
    AND old.model_id=p.model_id AND old.work_type=p.work_type AND old.resolution=p.resolution
    AND old.aspect_ratio=p.aspect_ratio AND old.output_count=p.output_count AND old.quality=q.quality),0),
  true,'20261030 ADX2: low=3, medium/auto=5, high=6; 1K/2K/4K same price'
FROM adx2_previous_prices p CROSS JOIN (VALUES ('low',3),('medium',5),('high',6)) q(quality,cost);
DO $$
BEGIN
  IF (SELECT count(*) FROM image_model_prices WHERE site_id=1 AND model_id IN (215,216) AND is_active) != 324
    OR (SELECT count(*) FROM (SELECT model_id,work_type,resolution,aspect_ratio,output_count,quality
        FROM image_model_prices WHERE site_id=1 AND model_id IN (215,216) AND is_active
        GROUP BY 1,2,3,4,5,6) specs) != 324 THEN
    RAISE EXCEPTION 'ADX2 quality matrix is incomplete or duplicated';
  END IF;
END $$;
COMMIT;
SELECT model_id,quality,min(credit_cost) AS minimum,max(credit_cost) AS maximum,count(*) AS specifications
FROM image_model_prices WHERE site_id=1 AND model_id IN (215,216) AND is_active GROUP BY 1,2 ORDER BY 1,2;
