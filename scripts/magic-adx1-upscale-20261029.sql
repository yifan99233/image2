-- Restore output tiers removed by the ADX1 1K-only configuration change.
-- Upstream conversion belongs to V4; these are customer-visible output tiers.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='20s';
SELECT id FROM image_models WHERE site_id=1 AND id IN(215,216,217,266,267) FOR UPDATE;
DO $$ BEGIN
 IF (SELECT count(*) FROM image_models WHERE site_id=1 AND provider_id=279 AND
 (id,vendor_model) IN ((215,'gpt-image-2-adx1'),(216,'gpt-image-2.5-flare-adx1'),(217,'gpt-image-2.5-sunburst-adx1'),(266,'nano-banana-2-adx1'),(267,'nano-banana-2.1-adx1')))<>5 THEN
 RAISE EXCEPTION 'Unexpected ADX1 identity'; END IF;
 IF (SELECT count(*) FROM image_resolution_specs WHERE site_id=1 AND code IN('1k','2k','4k') AND is_active)<>3 THEN
 RAISE EXCEPTION 'Missing output tier specification'; END IF;
END $$;
CREATE TEMP TABLE restore_upscale_prices(id bigint,model_id bigint,work_type text,resolution text,aspect_ratio text,output_count int,credit_cost numeric,fixed_surcharge numeric,version int) ON COMMIT DROP;
INSERT INTO restore_upscale_prices VALUES
 (7847,215,'image_to_image','4k','4:3',1,2,0.0,1),
 (7817,215,'text_to_image','2k','3:2',1,2,0.0,1),
 (7818,215,'text_to_image','2k','9:16',1,2,0.0,1),
 (7819,215,'text_to_image','2k','16:9',1,2,0.0,1),
 (7820,215,'text_to_image','2k','3:4',1,2,0.0,1),
 (7821,215,'text_to_image','2k','4:3',1,2,0.0,1),
 (7822,215,'text_to_image','2k','1:1',1,2,0.0,1),
 (7823,215,'text_to_image','2k','auto',1,2,0.0,1),
 (7824,215,'text_to_image','4k','auto',1,2,0.0,1),
 (7825,215,'text_to_image','4k','1:1',1,2,0.0,1),
 (7826,215,'text_to_image','4k','4:3',1,2,0.0,1),
 (7827,215,'text_to_image','4k','3:4',1,2,0.0,1),
 (7828,215,'text_to_image','4k','16:9',1,2,0.0,1),
 (7829,215,'text_to_image','4k','9:16',1,2,0.0,1),
 (7830,215,'text_to_image','4k','3:2',1,2,0.0,1),
 (7838,215,'image_to_image','2k','3:2',1,2,0.0,1),
 (7839,215,'image_to_image','2k','9:16',1,2,0.0,1),
 (7840,215,'image_to_image','2k','16:9',1,2,0.0,1),
 (7841,215,'image_to_image','2k','3:4',1,2,0.0,1),
 (7842,215,'image_to_image','2k','4:3',1,2,0.0,1),
 (7843,215,'image_to_image','2k','1:1',1,2,0.0,1),
 (7844,215,'image_to_image','2k','auto',1,2,0.0,1),
 (7845,215,'image_to_image','4k','auto',1,2,0.0,1),
 (7846,215,'image_to_image','4k','1:1',1,2,0.0,1),
 (7848,215,'image_to_image','4k','3:4',1,2,0.0,1),
 (7849,215,'image_to_image','4k','16:9',1,2,0.0,1),
 (7850,215,'image_to_image','4k','9:16',1,2,0.0,1),
 (7851,215,'image_to_image','4k','3:2',1,2,0.0,1),
 (7854,215,'text_to_image','2k','2:3',1,2,0.0,1),
 (7855,215,'text_to_image','2k','21:9',1,2,0.0,1),
 (7856,215,'text_to_image','4k','2:3',1,2,0.0,1),
 (7857,215,'text_to_image','4k','21:9',1,2,0.0,1),
 (7860,215,'image_to_image','2k','2:3',1,2,0.0,1),
 (7861,215,'image_to_image','2k','21:9',1,2,0.0,1),
 (7862,215,'image_to_image','4k','2:3',1,2,0.0,1),
 (7863,215,'image_to_image','4k','21:9',1,2,0.0,1),
 (7864,216,'image_to_image','4k','4:3',1,2,0.0,1),
 (7872,216,'text_to_image','2k','3:2',1,2,0.0,1),
 (7873,216,'text_to_image','2k','9:16',1,2,0.0,1),
 (7874,216,'text_to_image','2k','16:9',1,2,0.0,1),
 (7875,216,'text_to_image','2k','3:4',1,2,0.0,1),
 (7876,216,'text_to_image','2k','4:3',1,2,0.0,1),
 (7877,216,'text_to_image','2k','1:1',1,2,0.0,1),
 (7878,216,'text_to_image','2k','auto',1,2,0.0,1),
 (7879,216,'text_to_image','4k','auto',1,2,0.0,1),
 (7880,216,'text_to_image','4k','1:1',1,2,0.0,1),
 (7881,216,'text_to_image','4k','4:3',1,2,0.0,1),
 (7882,216,'text_to_image','4k','3:4',1,2,0.0,1),
 (7883,216,'text_to_image','4k','16:9',1,2,0.0,1),
 (7884,216,'text_to_image','4k','9:16',1,2,0.0,1),
 (7885,216,'text_to_image','4k','3:2',1,2,0.0,1),
 (7893,216,'image_to_image','2k','3:2',1,2,0.0,1),
 (7894,216,'image_to_image','2k','9:16',1,2,0.0,1),
 (7895,216,'image_to_image','2k','16:9',1,2,0.0,1),
 (7896,216,'image_to_image','2k','3:4',1,2,0.0,1),
 (7897,216,'image_to_image','2k','4:3',1,2,0.0,1),
 (7898,216,'image_to_image','2k','1:1',1,2,0.0,1),
 (7899,216,'image_to_image','2k','auto',1,2,0.0,1),
 (7900,216,'image_to_image','4k','auto',1,2,0.0,1),
 (7901,216,'image_to_image','4k','1:1',1,2,0.0,1),
 (7902,216,'image_to_image','4k','3:4',1,2,0.0,1),
 (7903,216,'image_to_image','4k','16:9',1,2,0.0,1),
 (7904,216,'image_to_image','4k','9:16',1,2,0.0,1),
 (7905,216,'image_to_image','4k','3:2',1,2,0.0,1),
 (7908,216,'text_to_image','2k','2:3',1,2,0.0,1),
 (7909,216,'text_to_image','2k','21:9',1,2,0.0,1),
 (7910,216,'text_to_image','4k','2:3',1,2,0.0,1),
 (7911,216,'text_to_image','4k','21:9',1,2,0.0,1),
 (7914,216,'image_to_image','2k','2:3',1,2,0.0,1),
 (7915,216,'image_to_image','2k','21:9',1,2,0.0,1),
 (7916,216,'image_to_image','4k','2:3',1,2,0.0,1),
 (7917,216,'image_to_image','4k','21:9',1,2,0.0,1),
 (7918,217,'image_to_image','4k','4:3',1,2,0.0,1),
 (7926,217,'text_to_image','2k','3:2',1,2,0.0,1),
 (7927,217,'text_to_image','2k','9:16',1,2,0.0,1),
 (7928,217,'text_to_image','2k','16:9',1,2,0.0,1),
 (7929,217,'text_to_image','2k','3:4',1,2,0.0,1),
 (7930,217,'text_to_image','2k','4:3',1,2,0.0,1),
 (7931,217,'text_to_image','2k','1:1',1,2,0.0,1),
 (7932,217,'text_to_image','2k','auto',1,2,0.0,1),
 (7933,217,'text_to_image','4k','auto',1,2,0.0,1),
 (7934,217,'text_to_image','4k','1:1',1,2,0.0,1),
 (7935,217,'text_to_image','4k','4:3',1,2,0.0,1),
 (7936,217,'text_to_image','4k','3:4',1,2,0.0,1),
 (7937,217,'text_to_image','4k','16:9',1,2,0.0,1),
 (7938,217,'text_to_image','4k','9:16',1,2,0.0,1),
 (7939,217,'text_to_image','4k','3:2',1,2,0.0,1),
 (7947,217,'image_to_image','2k','3:2',1,2,0.0,1),
 (7948,217,'image_to_image','2k','9:16',1,2,0.0,1),
 (7949,217,'image_to_image','2k','16:9',1,2,0.0,1),
 (7950,217,'image_to_image','2k','3:4',1,2,0.0,1),
 (7951,217,'image_to_image','2k','4:3',1,2,0.0,1),
 (7952,217,'image_to_image','2k','1:1',1,2,0.0,1),
 (7953,217,'image_to_image','2k','auto',1,2,0.0,1),
 (7954,217,'image_to_image','4k','auto',1,2,0.0,1),
 (7955,217,'image_to_image','4k','1:1',1,2,0.0,1),
 (7956,217,'image_to_image','4k','3:4',1,2,0.0,1),
 (7957,217,'image_to_image','4k','16:9',1,2,0.0,1),
 (7958,217,'image_to_image','4k','9:16',1,2,0.0,1),
 (7959,217,'image_to_image','4k','3:2',1,2,0.0,1),
 (7962,217,'text_to_image','2k','2:3',1,2,0.0,1),
 (7963,217,'text_to_image','2k','21:9',1,2,0.0,1),
 (7964,217,'text_to_image','4k','2:3',1,2,0.0,1),
 (7965,217,'text_to_image','4k','21:9',1,2,0.0,1),
 (7968,217,'image_to_image','2k','2:3',1,2,0.0,1),
 (7969,217,'image_to_image','2k','21:9',1,2,0.0,1),
 (7970,217,'image_to_image','4k','2:3',1,2,0.0,1),
 (7971,217,'image_to_image','4k','21:9',1,2,0.0,1),
 (8574,266,'text_to_image','2k','1:1',1,6,0.0,1),
 (8575,266,'text_to_image','2k','4:3',1,6,0.0,1),
 (8580,266,'text_to_image','2k','2:3',1,6,0.0,1),
 (8585,266,'text_to_image','4k','16:9',1,6,0.0,1),
 (8600,266,'image_to_image','2k','3:4',1,6,0.0,1),
 (8605,266,'image_to_image','2k','21:9',1,6,0.0,1),
 (8610,266,'image_to_image','4k','9:16',1,6,0.0,1),
 (8623,267,'text_to_image','2k','4:3',1,7,0.0,1),
 (8628,267,'text_to_image','2k','2:3',1,7,0.0,1),
 (8633,267,'text_to_image','4k','16:9',1,7,0.0,1),
 (8648,267,'image_to_image','2k','3:4',1,7,0.0,1),
 (8653,267,'image_to_image','2k','21:9',1,7,0.0,1),
 (8658,267,'image_to_image','4k','9:16',1,7,0.0,1),
 (8576,266,'text_to_image','2k','3:4',1,6,0.0,1),
 (8581,266,'text_to_image','2k','21:9',1,6,0.0,1),
 (8586,266,'text_to_image','4k','9:16',1,6,0.0,1),
 (8601,266,'image_to_image','2k','16:9',1,6,0.0,1),
 (8606,266,'image_to_image','4k','1:1',1,6,0.0,1),
 (8611,266,'image_to_image','4k','3:2',1,6,0.0,1),
 (8624,267,'text_to_image','2k','3:4',1,7,0.0,1),
 (8629,267,'text_to_image','2k','21:9',1,7,0.0,1),
 (8634,267,'text_to_image','4k','9:16',1,7,0.0,1),
 (8649,267,'image_to_image','2k','16:9',1,7,0.0,1),
 (8654,267,'image_to_image','4k','1:1',1,7,0.0,1),
 (8659,267,'image_to_image','4k','3:2',1,7,0.0,1),
 (8577,266,'text_to_image','2k','16:9',1,6,0.0,1),
 (8582,266,'text_to_image','4k','1:1',1,6,0.0,1),
 (8587,266,'text_to_image','4k','3:2',1,6,0.0,1),
 (8602,266,'image_to_image','2k','9:16',1,6,0.0,1),
 (8607,266,'image_to_image','4k','4:3',1,6,0.0,1),
 (8612,266,'image_to_image','4k','2:3',1,6,0.0,1),
 (8625,267,'text_to_image','2k','16:9',1,7,0.0,1),
 (8630,267,'text_to_image','4k','1:1',1,7,0.0,1),
 (8635,267,'text_to_image','4k','3:2',1,7,0.0,1),
 (8650,267,'image_to_image','2k','9:16',1,7,0.0,1),
 (8655,267,'image_to_image','4k','4:3',1,7,0.0,1),
 (8660,267,'image_to_image','4k','2:3',1,7,0.0,1),
 (8578,266,'text_to_image','2k','9:16',1,6,0.0,1),
 (8583,266,'text_to_image','4k','4:3',1,6,0.0,1),
 (8588,266,'text_to_image','4k','2:3',1,6,0.0,1),
 (8598,266,'image_to_image','2k','1:1',1,6,0.0,1),
 (8603,266,'image_to_image','2k','3:2',1,6,0.0,1),
 (8608,266,'image_to_image','4k','3:4',1,6,0.0,1),
 (8613,266,'image_to_image','4k','21:9',1,6,0.0,1),
 (8626,267,'text_to_image','2k','9:16',1,7,0.0,1),
 (8631,267,'text_to_image','4k','4:3',1,7,0.0,1),
 (8636,267,'text_to_image','4k','2:3',1,7,0.0,1),
 (8646,267,'image_to_image','2k','1:1',1,7,0.0,1),
 (8651,267,'image_to_image','2k','3:2',1,7,0.0,1),
 (8656,267,'image_to_image','4k','3:4',1,7,0.0,1),
 (8661,267,'image_to_image','4k','21:9',1,7,0.0,1),
 (8579,266,'text_to_image','2k','3:2',1,6,0.0,1),
 (8584,266,'text_to_image','4k','3:4',1,6,0.0,1),
 (8589,266,'text_to_image','4k','21:9',1,6,0.0,1),
 (8599,266,'image_to_image','2k','4:3',1,6,0.0,1),
 (8604,266,'image_to_image','2k','2:3',1,6,0.0,1),
 (8609,266,'image_to_image','4k','16:9',1,6,0.0,1),
 (8622,267,'text_to_image','2k','1:1',1,7,0.0,1),
 (8627,267,'text_to_image','2k','3:2',1,7,0.0,1),
 (8632,267,'text_to_image','4k','3:4',1,7,0.0,1),
 (8637,267,'text_to_image','4k','21:9',1,7,0.0,1),
 (8647,267,'image_to_image','2k','4:3',1,7,0.0,1),
 (8652,267,'image_to_image','2k','2:3',1,7,0.0,1),
 (8657,267,'image_to_image','4k','16:9',1,7,0.0,1);
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM restore_upscale_prices b LEFT JOIN image_model_prices p ON p.id=b.id
 WHERE p.id IS NULL OR p.site_id<>1 OR (p.model_id,p.work_type,p.resolution,p.aspect_ratio,p.output_count,p.credit_cost,p.fixed_surcharge,p.version)
 IS DISTINCT FROM (b.model_id,b.work_type,b.resolution,b.aspect_ratio,b.output_count,b.credit_cost,b.fixed_surcharge,b.version)) THEN
 RAISE EXCEPTION 'Price snapshot changed; review before restoring'; END IF;
END $$;
UPDATE image_model_prices p SET is_active=true,updated_at=now()
 FROM restore_upscale_prices b WHERE p.id=b.id AND NOT p.is_active;
INSERT INTO image_model_resolutions(model_id,resolution_id)
 SELECT m.id,r.id FROM image_models m CROSS JOIN image_resolution_specs r
 WHERE m.site_id=1 AND m.id IN(215,216,217,266,267) AND r.site_id=1 AND r.code IN('1k','2k','4k') AND r.is_active
 ON CONFLICT(model_id,resolution_id) DO NOTHING;
-- Newly exposed Banana ratios inherit each tier's existing square price.
INSERT INTO image_model_prices(site_id,model_id,work_type,resolution,aspect_ratio,output_count,credit_cost,fixed_surcharge,version,effective_at,is_active,change_reason)
 SELECT p.site_id,p.model_id,p.work_type,p.resolution,r.code,p.output_count,p.credit_cost,p.fixed_surcharge,
 COALESCE((SELECT max(old.version) FROM image_model_prices old WHERE old.site_id=1 AND old.model_id=p.model_id AND old.work_type=p.work_type AND old.resolution=p.resolution AND old.aspect_ratio=r.code AND old.output_count=p.output_count),0)+1,
 now(),true,'ADX1 输出分辨率恢复：比例沿用对应 2K/4K 积分，V4 网关负责超分'
 FROM (SELECT DISTINCT ON(model_id,work_type,resolution,output_count) * FROM image_model_prices
 WHERE site_id=1 AND model_id IN(266,267) AND resolution IN('2k','4k') AND aspect_ratio='1:1' AND is_active
 ORDER BY model_id,work_type,resolution,output_count,effective_at DESC,id DESC) p
 JOIN image_model_aspect_ratios mr ON mr.model_id=p.model_id JOIN image_aspect_ratio_specs r ON r.id=mr.aspect_ratio_id AND r.site_id=1 AND r.is_active
 WHERE NOT EXISTS(SELECT 1 FROM image_model_prices old WHERE old.site_id=1 AND old.model_id=p.model_id AND old.work_type=p.work_type AND old.resolution=p.resolution AND old.aspect_ratio=r.code AND old.output_count=p.output_count AND old.is_active);
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM image_models m JOIN image_model_resolutions mr ON mr.model_id=m.id JOIN image_resolution_specs res ON res.id=mr.resolution_id
 JOIN image_model_aspect_ratios ma ON ma.model_id=m.id JOIN image_aspect_ratio_specs ratio ON ratio.id=ma.aspect_ratio_id
 CROSS JOIN(VALUES('text_to_image'),('image_to_image')) w(work_type)
 WHERE m.id IN(215,216,217,266,267) AND NOT EXISTS(SELECT 1 FROM image_model_prices p WHERE p.model_id=m.id AND p.site_id=1 AND p.work_type=w.work_type AND p.resolution=res.code AND p.aspect_ratio=ratio.code AND p.output_count=1 AND p.is_active)) THEN
 RAISE EXCEPTION 'Incomplete restored pricing matrix'; END IF;
END $$;
COMMIT;
