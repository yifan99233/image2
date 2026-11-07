-- Operator-run configuration change; back up the affected rows before running.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='20s';
CREATE TEMP TABLE adx1_targets(id bigint PRIMARY KEY,old_model text,new_model text,max_refs integer) ON COMMIT DROP;
INSERT INTO adx1_targets VALUES
 (215,'gpt-image-2-adx','gpt-image-2-adx1',16),
 (216,'gpt-image-2.5-flare-adx','gpt-image-2.5-flare-adx1',16),
 (217,'gpt-image-2.5-sunburst-adx','gpt-image-2.5-sunburst-adx1',16),
 (266,'gemini-3.1-flash-image','nano-banana-2-adx1',14),
 (267,'gemini-nano-banana-2.1','nano-banana-2.1-adx1',14);
SELECT m.id FROM image_models m JOIN adx1_targets t ON t.id=m.id FOR UPDATE OF m;
DO $$ BEGIN
 IF (SELECT count(*) FROM image_model_providers WHERE id=279 AND site_id=1 AND base_url='https://agent.shyfai.com/v1' AND is_active AND auth_type='bearer')<>1 THEN
  RAISE EXCEPTION 'Unexpected NewAPI provider'; END IF;
 IF (SELECT count(*) FROM image_models m JOIN adx1_targets t ON t.id=m.id WHERE m.site_id=1 AND m.is_active AND m.vendor_model IN(t.old_model,t.new_model))<>5 THEN
  RAISE EXCEPTION 'Unexpected model identity'; END IF;
 IF (SELECT count(*) FROM image_resolution_specs WHERE site_id=1 AND code='1k' AND is_active)<>1 THEN
  RAISE EXCEPTION 'Missing 1K specification'; END IF;
END $$;
CREATE TEMP TABLE adx1_ratios(code text PRIMARY KEY,ordering integer) ON COMMIT DROP;
INSERT INTO adx1_ratios SELECT code,ord FROM unnest(ARRAY['auto','1:1','1:4','4:1','1:8','8:1','2:3','3:2','3:4','4:3','4:5','5:4','9:16','16:9','21:9']) WITH ORDINALITY AS r(code,ord);
INSERT INTO image_aspect_ratio_specs(site_id,code,label,sort_order,is_active)
 SELECT 1,code,CASE WHEN code='auto' THEN '自动' ELSE code END,200+ordering,true FROM adx1_ratios
 ON CONFLICT(site_id,code) DO NOTHING;
INSERT INTO image_model_aspect_ratios(model_id,aspect_ratio_id)
 SELECT m.id,r.id FROM image_models m CROSS JOIN image_aspect_ratio_specs r JOIN adx1_ratios a ON a.code=r.code
 WHERE m.id IN(266,267) AND m.site_id=1 AND r.site_id=1 AND r.is_active
 ON CONFLICT(model_id,aspect_ratio_id) DO NOTHING;
-- New ratios inherit the existing 1K square tariff. Historical rows remain.
INSERT INTO image_model_prices(site_id,model_id,work_type,resolution,aspect_ratio,output_count,credit_cost,fixed_surcharge,version,effective_at,is_active,change_reason)
 SELECT p.site_id,p.model_id,p.work_type,'1k',r.code,p.output_count,p.credit_cost,p.fixed_surcharge,
 COALESCE((SELECT max(old.version) FROM image_model_prices old WHERE old.site_id=1 AND old.model_id=p.model_id AND old.work_type=p.work_type AND old.resolution='1k' AND old.aspect_ratio=r.code AND old.output_count=p.output_count),0)+1,
 now(),true,'ADX1 接入：新增比例沿用现有 1K 积分'
 FROM (SELECT DISTINCT ON(model_id,work_type,output_count) * FROM image_model_prices
       WHERE site_id=1 AND model_id IN(266,267) AND resolution='1k' AND aspect_ratio='1:1' AND is_active
       ORDER BY model_id,work_type,output_count,effective_at DESC,id DESC) p CROSS JOIN adx1_ratios r
 WHERE NOT EXISTS(SELECT 1 FROM image_model_prices old WHERE old.site_id=1 AND old.model_id=p.model_id AND old.work_type=p.work_type AND old.resolution='1k' AND old.aspect_ratio=r.code AND old.output_count=p.output_count AND old.is_active);
DELETE FROM image_model_resolutions mr USING adx1_targets t,image_resolution_specs r
 WHERE mr.model_id=t.id AND mr.resolution_id=r.id AND r.code<>'1k';
INSERT INTO image_model_resolutions(model_id,resolution_id)
 SELECT t.id,r.id FROM adx1_targets t CROSS JOIN image_resolution_specs r WHERE r.site_id=1 AND r.code='1k'
 ON CONFLICT(model_id,resolution_id) DO NOTHING;
UPDATE image_model_prices p SET is_active=false,updated_at=now()
 FROM adx1_targets t WHERE p.model_id=t.id AND p.site_id=1 AND p.resolution<>'1k' AND p.is_active;
UPDATE image_models m SET provider_id=279,vendor_model=t.new_model,max_input_images=t.max_refs,supports_image_edit=true,
 name=CASE WHEN m.id IN(215,216,217) THEN replace(t.new_model,'-adx1','')||' (ADX1)' ELSE m.name END,updated_at=now()
 FROM adx1_targets t WHERE m.id=t.id AND m.site_id=1;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM adx1_targets t WHERE NOT EXISTS(SELECT 1 FROM image_model_prices p WHERE p.model_id=t.id AND p.site_id=1 AND p.resolution='1k' AND p.is_active)) THEN
  RAISE EXCEPTION 'Missing 1K tariff'; END IF;
 IF EXISTS(SELECT 1 FROM image_models m CROSS JOIN adx1_ratios r CROSS JOIN(VALUES('text_to_image'),('image_to_image')) w(work_type)
 WHERE m.id IN(266,267) AND NOT EXISTS(SELECT 1 FROM image_model_prices p WHERE p.model_id=m.id AND p.site_id=1 AND p.work_type=w.work_type AND p.resolution='1k' AND p.aspect_ratio=r.code AND p.output_count=1 AND p.is_active)) THEN
  RAISE EXCEPTION 'Incomplete Banana ratio pricing'; END IF;
END $$;
COMMIT;
