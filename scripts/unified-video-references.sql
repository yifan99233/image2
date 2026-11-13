-- Magic main site only. Run from the deployed Git checkout under maintenance,
-- after the user-server/user-web release and FF/Muse V4 media support are ready.
-- Preserve existing reference prices; fill missing specs from the current text
-- video price. Do not activate hidden/disabled models or firefly-veo31-fast.
\set ON_ERROR_STOP on
BEGIN;
SELECT pg_advisory_xact_lock(hashtext('magic-unified-video-references-20261110'));

CREATE TEMP TABLE unified_video_targets ON COMMIT DROP AS
SELECT id, site_id, vendor_model FROM image_models
WHERE site_id = 1 AND is_active AND is_public AND capability_type = 'video'
  AND vendor_model IN ('firefly-veo31-lite', 'firefly-omniflash', 'muse-video', 'muse-video-cdn')
  AND 'text_to_video' = ANY(string_to_array(work_type, ','));

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM unified_video_targets t WHERE NOT EXISTS (
    SELECT 1 FROM image_model_prices p WHERE p.site_id = t.site_id AND p.model_id = t.id
      AND p.work_type = 'text_to_video' AND p.is_active
  )) THEN RAISE EXCEPTION 'Video model has no active text video prices; review configuration before enabling references'; END IF;
END $$;

INSERT INTO image_model_prices(site_id, model_id, work_type, resolution, aspect_ratio, output_count,
  quality, credit_cost, fixed_surcharge, version, effective_at, is_active, change_reason)
SELECT p.site_id, p.model_id, 'image_to_video', p.resolution, p.aspect_ratio, p.output_count,
  p.quality, p.credit_cost, p.fixed_surcharge, p.version, p.effective_at, true,
  '统一视频入口：参考生成沿用当前同规格文生视频价格'
FROM (
  SELECT DISTINCT ON (p.site_id, p.model_id, p.resolution, p.aspect_ratio, p.output_count, p.quality) p.*
  FROM image_model_prices p JOIN unified_video_targets t ON p.site_id = t.site_id AND p.model_id = t.id
  WHERE p.work_type = 'text_to_video' AND p.is_active
  ORDER BY p.site_id, p.model_id, p.resolution, p.aspect_ratio, p.output_count, p.quality,
    p.effective_at DESC, p.id DESC
) p
WHERE NOT EXISTS (
  SELECT 1 FROM image_model_prices existing WHERE existing.site_id = p.site_id AND existing.model_id = p.model_id
    AND existing.work_type = 'image_to_video' AND existing.is_active
    AND existing.resolution = p.resolution AND existing.aspect_ratio = p.aspect_ratio
    AND existing.output_count = p.output_count AND existing.quality = p.quality
);

UPDATE image_models m SET
  work_type = CASE WHEN 'image_to_video' = ANY(string_to_array(m.work_type, ',')) THEN m.work_type
    ELSE m.work_type || ',image_to_video' END,
  max_input_images = CASE t.vendor_model WHEN 'firefly-veo31-lite' THEN 2 WHEN 'firefly-omniflash' THEN 10 ELSE 4 END,
  description = CASE t.vendor_model
    WHEN 'firefly-veo31-lite' THEN '文字生成视频，可选上传 PNG/JPG 首帧、尾帧。'
    WHEN 'firefly-omniflash' THEN '文字生成视频，可选上传图片或视频参考。'
    ELSE '文字生成视频，可选上传图片、视频或音频参考，最多 4 个、合计 24MB。' END
FROM unified_video_targets t WHERE m.id = t.id AND m.site_id = t.site_id;
COMMIT;
