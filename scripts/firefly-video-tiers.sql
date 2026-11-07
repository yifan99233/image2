-- User-confirmed video tiers, Magic main only. Apply under maintenance after FF/V4/Agent support.
\set ON_ERROR_STOP on
BEGIN;
SELECT pg_advisory_xact_lock(hashtext('magic-firefly-video-20261104'));
DO $$
DECLARE pid bigint; m bigint; item record; d int; r text;
BEGIN
 SELECT id INTO pid FROM image_model_providers WHERE site_id=1 AND code='firefly-video-agent';
 IF pid IS NULL THEN RAISE EXCEPTION 'FF provider missing'; END IF;
 INSERT INTO image_models(site_id,provider_id,name,code,vendor_model,work_type,description,capability_type,supports_image_edit,max_input_images,max_output_images,concurrency_limit,storage_mode,timeout_seconds,disable_retry,is_active,is_public,is_new)
 VALUES(1,pid,'FF · Gemini Omni Flash','firefly-omniflash','firefly-omniflash','text_to_video','音视频同生，0.30 元/条；暂不支持参考图。','video',false,0,1,500,'local',900,true,true,true,true)
 ON CONFLICT(site_id,code) DO NOTHING;
 INSERT INTO video_duration_specs(site_id,code,label,sort_order,is_active)
 SELECT 1,n::text,n::text||' 秒',n,true FROM generate_series(3,15)n ON CONFLICT(site_id,code) DO UPDATE SET sort_order=excluded.sort_order;
 FOR item IN SELECT * FROM (VALUES
  ('veo31-lite',ARRAY[4,6,8],ARRAY['720p','1080p']),
  ('veo31-fast',ARRAY[4,6,8],ARRAY['720p','1080p']),
  ('veo31',ARRAY[4,6,8],ARRAY['720p','1080p']),
  ('omniflash',ARRAY[3,4,5,6,7,8,9,10],ARRAY['720p']),
  ('kling3',ARRAY[3,4,5,6,7,8,9,10,11,12,13,14,15],ARRAY['720p']),
  ('ray314',ARRAY[5,10],ARRAY['720p'])
 )v(code,durations,resolutions) LOOP
  SELECT id INTO m FROM image_models WHERE site_id=1 AND provider_id=pid AND code='firefly-'||item.code AND vendor_model='firefly-'||item.code;
  IF m IS NULL THEN RAISE EXCEPTION 'FF model missing: %',item.code; END IF;
  DELETE FROM image_model_resolutions WHERE model_id=m;
  INSERT INTO image_model_resolutions(model_id,resolution_id) SELECT m,id FROM image_resolution_specs WHERE site_id=1 AND code=ANY(item.resolutions);
  DELETE FROM image_model_durations WHERE model_id=m;
  INSERT INTO image_model_durations(model_id,duration_id) SELECT m,id FROM video_duration_specs WHERE site_id=1 AND code::text=ANY(ARRAY(SELECT x::text FROM unnest(item.durations)x));
  INSERT INTO image_model_aspect_ratios(model_id,aspect_ratio_id) SELECT m,id FROM image_aspect_ratio_specs WHERE site_id=1 AND code IN ('16:9','9:16','1:1') ON CONFLICT DO NOTHING;
  UPDATE image_model_prices SET is_active=false WHERE model_id=m;
  FOREACH r IN ARRAY item.resolutions LOOP
   FOREACH d IN ARRAY item.durations LOOP
    UPDATE image_model_prices SET is_active=true,credit_cost=0,fixed_surcharge=30
     WHERE model_id=m AND site_id=1 AND work_type='text_to_video' AND resolution=r AND aspect_ratio=d::text AND output_count=1 AND quality='any';
    IF NOT FOUND THEN
     INSERT INTO image_model_prices(site_id,model_id,work_type,resolution,aspect_ratio,output_count,credit_cost,fixed_surcharge,quality,version,change_reason)
      VALUES(1,m,'text_to_video',r,d::text,1,0,30,'any',1,'按实际可用视频档位，统一 0.30 元/条');
    END IF;
   END LOOP;
  END LOOP;
 END LOOP;
 -- Retain old model identities and ongoing jobs; remove only from the public catalog.
 UPDATE image_models SET is_public=false WHERE site_id=1 AND provider_id=pid AND code IN ('firefly-kling3omni','firefly-ray3');
END $$;
COMMIT;
