-- Main Magic only: Muse supports 60 seconds; standard tariff is 2.5 credits/second.
-- Existing membership discounts continue to apply. Historic task snapshots are unchanged.
\set ON_ERROR_STOP on
BEGIN;
SELECT pg_advisory_xact_lock(hashtext('magic-muse-duration-60-20261112'));
DO $$
BEGIN
  IF (SELECT count(*) FROM image_models WHERE site_id=1 AND vendor_model IN ('muse-video','muse-video-cdn') AND is_active) <> 2 THEN
    RAISE EXCEPTION 'expected two active main-site Muse video models';
  END IF;
  IF EXISTS (
    SELECT 1 FROM image_models m WHERE m.site_id=1 AND m.vendor_model IN ('muse-video','muse-video-cdn') AND m.is_active
    AND NOT EXISTS (SELECT 1 FROM image_model_prices p WHERE p.model_id=m.id AND p.is_active AND p.aspect_ratio='10')
  ) THEN RAISE EXCEPTION 'missing 10-second base tariff'; END IF;
END $$;
INSERT INTO video_duration_specs(site_id,code,label,sort_order,is_active)
  SELECT 1,n::text,n::text||' 秒',n,true FROM unnest(ARRAY[20,30,40,50,60]) n
  ON CONFLICT(site_id,code) DO NOTHING;
INSERT INTO image_model_durations(model_id,duration_id)
  SELECT m.id,d.id FROM image_models m JOIN video_duration_specs d ON d.site_id=m.site_id
  WHERE m.site_id=1 AND m.vendor_model IN ('muse-video','muse-video-cdn') AND m.is_active
    AND d.code IN ('20','30','40','50','60') AND d.is_active
  ON CONFLICT DO NOTHING;
CREATE TEMP TABLE muse_duration_prices ON COMMIT DROP AS
  SELECT DISTINCT ON (p.model_id,p.work_type,p.resolution,n,p.output_count,p.quality)
    p.site_id,p.model_id,p.work_type,p.resolution,n::text AS duration,p.output_count,
    (2.5*n)::integer AS credit_cost,p.quality
  FROM image_model_prices p JOIN image_models m ON m.id=p.model_id
    CROSS JOIN unnest(ARRAY[6,10,20,30,40,50,60]) n
  WHERE m.site_id=1 AND m.vendor_model IN ('muse-video','muse-video-cdn') AND m.is_active
    AND p.site_id=1 AND p.is_active AND p.aspect_ratio='10'
  ORDER BY p.model_id,p.work_type,p.resolution,n,p.output_count,p.quality,p.effective_at DESC,p.id DESC;
UPDATE image_model_prices p SET is_active=false,updated_at=now()
  FROM muse_duration_prices d WHERE p.model_id=d.model_id AND p.site_id=d.site_id
    AND p.work_type=d.work_type AND p.resolution=d.resolution AND p.aspect_ratio=d.duration
    AND p.output_count=d.output_count AND p.quality=d.quality AND p.is_active
    AND (p.credit_cost<>d.credit_cost OR p.fixed_surcharge<>0);
INSERT INTO image_model_prices(site_id,model_id,work_type,resolution,aspect_ratio,output_count,
  credit_cost,fixed_surcharge,quality,version,change_reason)
  SELECT d.site_id,d.model_id,d.work_type,d.resolution,d.duration,d.output_count,
    d.credit_cost,0,d.quality,
    COALESCE((SELECT max(p.version) FROM image_model_prices p WHERE p.model_id=d.model_id
      AND p.work_type=d.work_type AND p.resolution=d.resolution AND p.aspect_ratio=d.duration
      AND p.output_count=d.output_count AND p.quality=d.quality),0)+1,
    'Muse 视频标准价 2.5 积分/秒，最长 60 秒'
  FROM muse_duration_prices d WHERE NOT EXISTS (
    SELECT 1 FROM image_model_prices p WHERE p.model_id=d.model_id AND p.site_id=d.site_id
      AND p.work_type=d.work_type AND p.resolution=d.resolution AND p.aspect_ratio=d.duration
      AND p.output_count=d.output_count AND p.quality=d.quality AND p.is_active);
COMMIT;
