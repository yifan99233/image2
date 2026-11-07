\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='20s';
DO $$ BEGIN
 IF (SELECT count(*) FROM image_models WHERE site_id=1 AND provider_id=279 AND
 (id,vendor_model) IN ((215,'gpt-image-2-adx1'),(216,'gpt-image-2.5-flare-adx1'),(217,'gpt-image-2.5-sunburst-adx1'),(266,'nano-banana-2-adx1'),(267,'nano-banana-2.1-adx1')))<>5 THEN
 RAISE EXCEPTION 'Unexpected ADX1 identity'; END IF;
END $$;
-- New tasks need time for the 300-second node budget plus gateway delivery.
-- Existing tasks keep their original deadline and billing state.
UPDATE image_models SET timeout_seconds=GREATEST(timeout_seconds,600)
 WHERE site_id=1 AND provider_id=279 AND id IN(215,216,217,266,267);
COMMIT;
