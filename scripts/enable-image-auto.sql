-- Opt-in configuration, not an automatic migration. Run with psql variables:
-- -v site_id=1 -v model_ids=57,150,151 -v baseline_resolution=1k -v apply=false
-- Review the dry-run output before rerunning with apply=true.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT set_config('image2.auto_site_id', :'site_id', true),
       set_config('image2.auto_model_ids', :'model_ids', true),
       set_config('image2.auto_baseline', :'baseline_resolution', true);

CREATE TEMP TABLE auto_models ON COMMIT DROP AS
SELECT id, site_id, name FROM image_models
WHERE site_id = current_setting('image2.auto_site_id')::bigint
  AND id = ANY(string_to_array(current_setting('image2.auto_model_ids'), ',')::bigint[])
  AND is_active AND vendor_model ~ '^gpt-image-2(\.5)?($|-)';

DO $$
BEGIN
  IF (SELECT count(*) FROM auto_models) = 0 OR
     (SELECT count(*) FROM auto_models) <> cardinality(string_to_array(current_setting('image2.auto_model_ids'), ',')) THEN
    RAISE EXCEPTION 'Target models must be unique, active GPT Image 2/2.5 models in the selected site';
  END IF;
  IF EXISTS (SELECT 1 FROM image_resolution_specs WHERE site_id = current_setting('image2.auto_site_id')::bigint AND code = 'auto' AND NOT is_active)
     OR EXISTS (SELECT 1 FROM image_aspect_ratio_specs WHERE site_id = current_setting('image2.auto_site_id')::bigint AND code = 'auto' AND NOT is_active) THEN
    RAISE EXCEPTION 'Auto was explicitly disabled; review its configuration first';
  END IF;
END $$;

-- Serialize this operation with model/price administration. Existing prices
-- are never updated; any error rolls back specs, associations and new prices.
LOCK TABLE image_models, image_model_prices, image_model_resolutions,
           image_model_aspect_ratios IN SHARE ROW EXCLUSIVE MODE;
CREATE TEMP TABLE auto_source_prices ON COMMIT DROP AS
SELECT DISTINCT ON (p.model_id, p.work_type, p.resolution, p.aspect_ratio, p.output_count)
       p.*
FROM image_model_prices p JOIN auto_models m ON m.id = p.model_id AND m.site_id = p.site_id
WHERE p.is_active AND p.resolution <> 'auto' AND p.aspect_ratio <> 'auto'
ORDER BY p.model_id, p.work_type, p.resolution, p.aspect_ratio, p.output_count,
         p.effective_at DESC, p.id DESC;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM auto_models m WHERE NOT EXISTS (
      SELECT 1 FROM auto_source_prices p WHERE p.model_id=m.id
        AND p.resolution=current_setting('image2.auto_baseline') AND p.aspect_ratio='1:1'
    )
  ) THEN RAISE EXCEPTION 'Each target needs an active baseline-resolution 1:1 price'; END IF;
  IF EXISTS (
    SELECT 1 FROM auto_source_prices GROUP BY model_id, work_type, resolution, output_count
    HAVING min(credit_cost) <> max(credit_cost)
       OR count(*) FILTER (WHERE aspect_ratio='1:1') <> 1
  ) THEN RAISE EXCEPTION 'Aspect-dependent or missing square prices require explicit Auto pricing'; END IF;
  IF EXISTS (
    SELECT 1 FROM auto_source_prices p WHERE NOT EXISTS (
      SELECT 1 FROM auto_source_prices b WHERE b.model_id=p.model_id
        AND b.work_type=p.work_type AND b.output_count=p.output_count
        AND b.resolution=current_setting('image2.auto_baseline') AND b.aspect_ratio=p.aspect_ratio
    )
  ) THEN RAISE EXCEPTION 'Baseline prices must cover all work types, output counts and ratios'; END IF;
END $$;

INSERT INTO image_resolution_specs (site_id, code, label, sort_order, is_active)
VALUES (current_setting('image2.auto_site_id')::bigint, 'auto', '自动（Auto）', 0, true)
ON CONFLICT (site_id, code) DO NOTHING;
INSERT INTO image_aspect_ratio_specs (site_id, code, label, sort_order, is_active)
VALUES (current_setting('image2.auto_site_id')::bigint, 'auto', '自动（Auto）', 0, true)
ON CONFLICT (site_id, code) DO NOTHING;
INSERT INTO image_model_resolutions (model_id, resolution_id)
SELECT m.id, s.id FROM auto_models m JOIN image_resolution_specs s ON s.site_id=m.site_id AND s.code='auto'
ON CONFLICT (model_id, resolution_id) DO NOTHING;
INSERT INTO image_model_aspect_ratios (model_id, aspect_ratio_id)
SELECT m.id, s.id FROM auto_models m JOIN image_aspect_ratio_specs s ON s.site_id=m.site_id AND s.code='auto'
ON CONFLICT (model_id, aspect_ratio_id) DO NOTHING;

CREATE TEMP TABLE auto_new_prices ON COMMIT DROP AS
WITH candidates AS (
  SELECT site_id, model_id, work_type, 'auto'::varchar AS resolution, aspect_ratio, output_count, credit_cost
  FROM auto_source_prices WHERE resolution=current_setting('image2.auto_baseline')
  UNION ALL
  SELECT site_id, model_id, work_type, resolution, 'auto', output_count, credit_cost
  FROM auto_source_prices WHERE aspect_ratio='1:1'
  UNION ALL
  SELECT site_id, model_id, work_type, 'auto', 'auto', output_count, credit_cost
  FROM auto_source_prices WHERE resolution=current_setting('image2.auto_baseline') AND aspect_ratio='1:1'
), inserted AS (
  INSERT INTO image_model_prices (site_id, model_id, work_type, resolution, aspect_ratio, output_count,
                                 credit_cost, version, is_active, change_reason)
  SELECT c.site_id, c.model_id, c.work_type, c.resolution, c.aspect_ratio, c.output_count,
         c.credit_cost, COALESCE((SELECT max(p.version) FROM image_model_prices p WHERE p.model_id=c.model_id), 0)+1,
         true, 'Enable Auto size; resolution Auto uses ' || current_setting('image2.auto_baseline') || ' pricing; ratio Auto preserves resolution pricing'
  FROM candidates c WHERE NOT EXISTS (
    SELECT 1 FROM image_model_prices p WHERE p.site_id=c.site_id AND p.model_id=c.model_id
      AND p.work_type=c.work_type AND p.resolution=c.resolution AND p.aspect_ratio=c.aspect_ratio
      AND p.output_count=c.output_count
  ) RETURNING model_id, work_type, resolution, aspect_ratio, output_count, credit_cost
) SELECT * FROM inserted;

SELECT m.id AS model_id, m.name, p.work_type, p.resolution, min(p.credit_cost) AS min_credits,
       max(p.credit_cost) AS max_credits, count(*) AS new_price_rows
FROM auto_new_prices p JOIN auto_models m ON m.id=p.model_id
GROUP BY m.id,m.name,p.work_type,p.resolution ORDER BY 1,3,4;
\if :apply
COMMIT;
\else
ROLLBACK;
\endif
