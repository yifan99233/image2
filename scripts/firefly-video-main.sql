-- Magic main only. Enable after Agent + V4 smoke test and under maintenance.
-- Main wallet: 1 CNY = 1 Agent balance unit = 100 displayed credits.
-- Fixed surcharge makes every output 30 credits even for VIP memberships.
\set ON_ERROR_STOP on
BEGIN;
SELECT pg_advisory_xact_lock(hashtext('magic-firefly-video-20261104'));
DO $$
DECLARE provider bigint; m bigint; item record; d text; r text;
BEGIN
  IF NOT EXISTS(SELECT 1 FROM agent_configs WHERE site_id=1 AND image_billing_enabled AND credit_to_agent_rate=100) THEN
    RAISE EXCEPTION 'main wallet conversion differs';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM image_model_providers WHERE id=279 AND site_id=1 AND base_url='https://agent.shyfai.com/v1' AND is_active) THEN
    RAISE EXCEPTION 'expected Agent provider missing';
  END IF;
  INSERT INTO image_model_providers(site_id,name,code,base_url,auth_type,encrypted_api_key,timeout_seconds,retry_count,is_active,access_mode)
    SELECT 1,'Firefly 视频','firefly-video-agent',base_url,auth_type,encrypted_api_key,900,0,true,access_mode
    FROM image_model_providers WHERE id=279
    ON CONFLICT(site_id,code) DO NOTHING;
  SELECT id INTO provider FROM image_model_providers WHERE site_id=1 AND code='firefly-video-agent';
  INSERT INTO image_resolution_specs(site_id,code,label,sort_order,is_active) VALUES(1,'720p','720P',20,true),(1,'1080p','1080P',30,true)
    ON CONFLICT(site_id,code) DO NOTHING;
  INSERT INTO image_aspect_ratio_specs(site_id,code,label,sort_order,is_active) VALUES(1,'16:9','16:9',10,true),(1,'9:16','9:16',20,true),(1,'1:1','1:1',30,true)
    ON CONFLICT(site_id,code) DO NOTHING;
  INSERT INTO video_duration_specs(site_id,code,label,sort_order,is_active)
    SELECT 1,n::text,n::text||' 秒',n,true FROM unnest(ARRAY[4,5,8,10,15])n ON CONFLICT(site_id,code) DO NOTHING;
  FOR item IN SELECT * FROM (VALUES
    ('veo31-lite','FF · Veo 3.1 Lite'),('veo31-fast','FF · Veo 3.1 Fast'),('veo31','FF · Veo 3.1'),
    ('kling3','FF · Kling 3.0'),('kling3omni','FF · Kling V3 Omni'),('ray314','FF · Luma Ray3.14'),('ray3','FF · Luma Ray3')
  )v(code,name) LOOP
    INSERT INTO image_models(site_id,provider_id,name,code,vendor_model,work_type,description,capability_type,supports_image_edit,max_input_images,max_output_images,concurrency_limit,storage_mode,timeout_seconds,disable_retry,is_active,is_public,is_new)
    VALUES(1,provider,item.name,'firefly-'||item.code,'firefly-'||item.code,'text_to_video','音视频同生，0.30 元/条；暂不支持参考图。','video',false,0,1,500,'local',900,true,true,true,true)
    ON CONFLICT(site_id,code) DO NOTHING;
    SELECT id INTO m FROM image_models WHERE site_id=1 AND code='firefly-'||item.code AND provider_id=provider AND vendor_model='firefly-'||item.code;
    IF m IS NULL THEN RAISE EXCEPTION 'existing FF video model identity differs'; END IF;
    INSERT INTO image_model_resolutions(model_id,resolution_id)
      SELECT m,id FROM image_resolution_specs WHERE site_id=1 AND code IN ('720p','1080p') ON CONFLICT DO NOTHING;
    INSERT INTO image_model_aspect_ratios(model_id,aspect_ratio_id)
      SELECT m,id FROM image_aspect_ratio_specs WHERE site_id=1 AND code IN ('16:9','9:16','1:1') ON CONFLICT DO NOTHING;
    FOR d IN SELECT unnest(CASE WHEN item.code LIKE 'kling%' THEN ARRAY['5','10','15'] ELSE ARRAY['4','8'] END) LOOP
      INSERT INTO image_model_durations(model_id,duration_id)
        SELECT m,id FROM video_duration_specs WHERE site_id=1 AND code=d ON CONFLICT DO NOTHING;
      FOREACH r IN ARRAY ARRAY['720p','1080p'] LOOP
        IF NOT EXISTS(SELECT 1 FROM image_model_prices WHERE model_id=m AND work_type='text_to_video' AND resolution=r AND aspect_ratio=d AND is_active) THEN
          INSERT INTO image_model_prices(site_id,model_id,work_type,resolution,aspect_ratio,output_count,credit_cost,fixed_surcharge,quality,version,change_reason)
            VALUES(1,m,'text_to_video',r,d,1,0,30,'any',1,'FF 视频统一 0.30 元/条');
        END IF;
      END LOOP;
    END LOOP;
  END LOOP;
END $$;
COMMIT;
SELECT m.code,p.resolution,p.aspect_ratio,p.credit_cost+p.fixed_surcharge AS credits
  FROM image_models m JOIN image_model_prices p ON p.model_id=m.id
  WHERE m.site_id=1 AND m.provider_id=(SELECT id FROM image_model_providers WHERE site_id=1 AND code='firefly-video-agent') AND p.is_active ORDER BY m.code,p.resolution,p.aspect_ratio;
