-- Operator-run after private configuration backup, maintenance, and task drain.
-- Display labels and ADX2 capabilities follow site 1; historical task/pricing rows remain.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout='10s';
SET LOCAL statement_timeout='60s';
LOCK TABLE site_configs,image_model_providers,image_models,image_model_prices,image_resolution_specs,
 image_aspect_ratio_specs,image_model_resolutions,image_model_aspect_ratios IN SHARE ROW EXCLUSIVE MODE;
DO $$
DECLARE t text; seq text; current_value bigint; highest bigint;
BEGIN
 IF (SELECT array_agg(id ORDER BY id) FROM site_configs) <> ARRAY[1,2,3,4,5,6,7,8,9,10]::bigint[] THEN
  RAISE EXCEPTION 'Site inventory changed; review the target scope'; END IF;
 IF (SELECT count(*) FROM image_models WHERE site_id=1 AND provider_id=279 AND is_active AND is_public AND storage_mode='native'
  AND ((id=215 AND vendor_model='gpt-image-2-adx2') OR (id=216 AND vendor_model='gpt-image-2.5-flare-adx2')
   OR (id=266 AND vendor_model='nano-banana-2-adx2') OR (id=267 AND vendor_model='nano-banana-2.1-adx2'))) <> 4 THEN
  RAISE EXCEPTION 'Source ADX2 models changed'; END IF;
 IF NOT EXISTS(SELECT 1 FROM image_model_providers WHERE id=279 AND site_id=1 AND code='agent-adx'
   AND base_url='https://agent.shyfai.com/v1' AND is_active) THEN RAISE EXCEPTION 'Source provider changed'; END IF;
 IF EXISTS(SELECT 1 FROM image_model_providers p CROSS JOIN image_model_providers source WHERE source.id=279
  AND p.site_id<>1 AND p.code=source.code AND
  (p.base_url,p.auth_type,p.access_mode,p.encrypted_api_key,p.timeout_seconds,p.retry_count)
   IS DISTINCT FROM (source.base_url,source.auth_type,source.access_mode,source.encrypted_api_key,source.timeout_seconds,source.retry_count)) THEN
  RAISE EXCEPTION 'Existing tenant provider differs; do not overwrite unrelated credentials'; END IF;
 -- Imported IDs can outpace their sequences; never move an existing sequence backward.
 FOREACH t IN ARRAY ARRAY['image_model_providers','image_models','image_model_prices','image_resolution_specs','image_aspect_ratio_specs','image_model_resolutions','image_model_aspect_ratios','admin_audit_logs'] LOOP
  seq:=pg_get_serial_sequence(t,'id');
  IF seq IS NOT NULL THEN
   EXECUTE format('SELECT last_value FROM %s',seq) INTO current_value;
   EXECUTE format('SELECT coalesce(max(id),0) FROM %I',t) INTO highest;
   PERFORM setval(seq,GREATEST(current_value,highest,1),true);
  END IF;
 END LOOP;
END $$;
CREATE TEMP TABLE native_sync_sources ON COMMIT DROP AS SELECT * FROM image_models WHERE site_id=1 AND id IN(215,216,266,267);
UPDATE image_models SET name=CASE id WHEN 215 THEN 'gpt-image-2 (原生)' WHEN 216 THEN 'gpt-image-2.5-flare (原生)' END,updated_at=now()
WHERE site_id=1 AND id IN(215,216);
UPDATE native_sync_sources s SET name=m.name FROM image_models m WHERE m.id=s.id;
INSERT INTO image_model_providers(site_id,name,code,base_url,access_mode,auth_type,encrypted_api_key,timeout_seconds,retry_count,is_active)
 SELECT site.id,p.name,p.code,p.base_url,p.access_mode,p.auth_type,p.encrypted_api_key,p.timeout_seconds,p.retry_count,true
 FROM site_configs site CROSS JOIN image_model_providers p WHERE site.id<>1 AND p.id=279
 ON CONFLICT(site_id,code) DO UPDATE SET is_active=true,updated_at=now();
INSERT INTO image_models(site_id,provider_id,name,code,vendor_model,work_type,capability_type,supports_image_edit,description,
 is_recommended,is_stable,is_new,speed_hint,risk_hint,max_input_images,max_output_images,concurrency_limit,sort_order,
 is_active,is_public,storage_mode,timeout_seconds,disable_retry)
 SELECT site.id,p.id,s.name,s.code,s.vendor_model,s.work_type,s.capability_type,s.supports_image_edit,s.description,
 s.is_recommended,s.is_stable,s.is_new,s.speed_hint,s.risk_hint,s.max_input_images,s.max_output_images,s.concurrency_limit,s.sort_order,
 s.is_active,s.is_public,s.storage_mode,s.timeout_seconds,s.disable_retry
 FROM site_configs site CROSS JOIN native_sync_sources s JOIN image_model_providers p ON p.site_id=site.id AND p.code='agent-adx'
 WHERE site.id<>1
 ON CONFLICT(site_id,code) DO UPDATE SET provider_id=excluded.provider_id,name=excluded.name,vendor_model=excluded.vendor_model,
 work_type=excluded.work_type,capability_type=excluded.capability_type,supports_image_edit=excluded.supports_image_edit,description=excluded.description,
 is_recommended=excluded.is_recommended,is_stable=excluded.is_stable,is_new=excluded.is_new,speed_hint=excluded.speed_hint,risk_hint=excluded.risk_hint,
 max_input_images=excluded.max_input_images,max_output_images=excluded.max_output_images,concurrency_limit=excluded.concurrency_limit,
 sort_order=excluded.sort_order,is_active=excluded.is_active,is_public=excluded.is_public,storage_mode=excluded.storage_mode,
 timeout_seconds=excluded.timeout_seconds,disable_retry=excluded.disable_retry,updated_at=now();
CREATE TEMP TABLE native_sync_targets ON COMMIT DROP AS
 SELECT m.id,m.site_id,s.id AS source_id FROM image_models m JOIN native_sync_sources s ON s.code=m.code WHERE m.site_id<>1;
-- Complete tenant-scoped option catalogs; retain existing labels and ordering.
INSERT INTO image_resolution_specs(site_id,code,label,sort_order,is_active)
 SELECT DISTINCT target.site_id,r.code,r.label,r.sort_order,true FROM native_sync_targets target
 JOIN image_model_resolutions mr ON mr.model_id=target.source_id JOIN image_resolution_specs r ON r.id=mr.resolution_id
 ON CONFLICT(site_id,code) DO UPDATE SET is_active=true,updated_at=now();
INSERT INTO image_aspect_ratio_specs(site_id,code,label,sort_order,is_active)
 SELECT DISTINCT target.site_id,r.code,r.label,r.sort_order,true FROM native_sync_targets target
 JOIN image_model_aspect_ratios mr ON mr.model_id=target.source_id JOIN image_aspect_ratio_specs r ON r.id=mr.aspect_ratio_id
 ON CONFLICT(site_id,code) DO UPDATE SET is_active=true,updated_at=now();
DELETE FROM image_model_resolutions WHERE model_id IN(SELECT id FROM native_sync_targets);
INSERT INTO image_model_resolutions(model_id,resolution_id)
 SELECT t.id,tr.id FROM native_sync_targets t JOIN image_model_resolutions mr ON mr.model_id=t.source_id
 JOIN image_resolution_specs sr ON sr.id=mr.resolution_id JOIN image_resolution_specs tr ON tr.site_id=t.site_id AND tr.code=sr.code;
DELETE FROM image_model_aspect_ratios WHERE model_id IN(SELECT id FROM native_sync_targets);
INSERT INTO image_model_aspect_ratios(model_id,aspect_ratio_id)
 SELECT t.id,tr.id FROM native_sync_targets t JOIN image_model_aspect_ratios mr ON mr.model_id=t.source_id
 JOIN image_aspect_ratio_specs sr ON sr.id=mr.aspect_ratio_id JOIN image_aspect_ratio_specs tr ON tr.site_id=t.site_id AND tr.code=sr.code;
-- Version the synchronized tariffs; never change accepted task prices or old price amounts.
UPDATE image_model_prices SET is_active=false,updated_at=now() WHERE model_id IN(SELECT id FROM native_sync_targets) AND is_active;
INSERT INTO image_model_prices(site_id,model_id,work_type,resolution,aspect_ratio,output_count,quality,credit_cost,fixed_surcharge,version,is_active,change_reason)
 SELECT t.site_id,t.id,p.work_type,p.resolution,p.aspect_ratio,p.output_count,p.quality,p.credit_cost,p.fixed_surcharge,
 1+coalesce((SELECT max(old.version) FROM image_model_prices old WHERE old.site_id=t.site_id AND old.model_id=t.id AND old.work_type=p.work_type
  AND old.resolution=p.resolution AND old.aspect_ratio=p.aspect_ratio AND old.output_count=p.output_count AND old.quality=p.quality),0),
 true,'20261030 同步主站原生 Image / ADX2 Banana 模型及价格'
 FROM native_sync_targets t JOIN image_model_prices p ON p.model_id=t.source_id AND p.site_id=1 AND p.is_active;
-- The retired Sunburst route is unavailable in ADX2; follow the main site's disabled state.
UPDATE image_models SET is_active=false,updated_at=now() WHERE site_id<>1 AND code='gpt-image-2.5-sunburst-adx' AND is_active
 AND EXISTS(SELECT 1 FROM image_models WHERE site_id=1 AND id=217 AND NOT is_active);
INSERT INTO admin_audit_logs(admin_username,action,resource_type,resource_id,reason)
 SELECT 'operator','sync_native_adx2','site_configs',id::text,'同步4款ADX2模型、规格、质量价格与CDN；Image显示标签改为原生，香蕉名称保持不变'
 FROM site_configs;
DO $$ BEGIN
 IF (SELECT count(*) FROM native_sync_targets)<>36 THEN RAISE EXCEPTION 'Expected 4 models on each of 9 subsites'; END IF;
 IF EXISTS(SELECT 1 FROM native_sync_targets t WHERE
  (SELECT count(*) FROM image_model_prices WHERE model_id=t.id AND is_active) <>
  (SELECT count(*) FROM image_model_prices WHERE model_id=t.source_id AND is_active)) THEN RAISE EXCEPTION 'Price synchronization incomplete'; END IF;
 IF EXISTS(SELECT 1 FROM native_sync_targets t JOIN image_models m ON m.id=t.id JOIN image_model_providers p ON p.id=m.provider_id
  WHERE p.site_id<>m.site_id OR NOT m.is_active OR NOT m.is_public OR m.storage_mode<>'native') THEN RAISE EXCEPTION 'Invalid tenant route'; END IF;
END $$;
COMMIT;
SELECT m.site_id,m.id,m.name,m.vendor_model,count(p.id) FILTER(WHERE p.is_active) AS prices
FROM image_models m JOIN image_model_prices p ON p.model_id=m.id
WHERE m.code IN('gpt-image-2-adx','gpt-image-2.5-flare-adx','banana-2-adx','banana-2.1-adx')
GROUP BY m.id ORDER BY m.site_id,m.id;
