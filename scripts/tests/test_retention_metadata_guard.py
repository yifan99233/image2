"""Regression checks against an isolated local PostgreSQL database."""
import ast
import os
from pathlib import Path
import subprocess
import unittest
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = "alembic/versions/20261106_0100_retention_metadata_guard.py"
ASSET = "a" * 32 + ".png"
OTHER = "b" * 32 + ".png"
URL = "https://magic.shyfai.cn/image2-assets/generated/1/" + ASSET

def literals(path):
    return {n.targets[0].id: ast.literal_eval(n.value)
            for n in ast.parse(path.read_text()).body
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)}

class RetentionGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ["MAGIC_RETENTION_TEST_DATABASE_URL"]
        parsed = urlparse(cls.dsn)
        if parsed.hostname not in (None, "localhost", "127.0.0.1") or "test" not in parsed.path:
            raise RuntimeError("Use an isolated local test database")
        cls.values = literals(ROOT / "user-server" / MIGRATION)
        cls.guard = cls.values["GUARD"]
        cls.setup = """
BEGIN;
CREATE SCHEMA retention_guard_regression;
SET LOCAL search_path=retention_guard_regression;
CREATE TABLE image_assets(id bigint PRIMARY KEY,storage_key text,retention_pending_at timestamptz);
CREATE TABLE image_tasks(
 id bigint PRIMARY KEY,input_image_url text,input_image_urls text,
 is_collected boolean NOT NULL DEFAULT false,is_gallery_featured boolean NOT NULL DEFAULT false,
 output_image_url text,output_image_r2_url text,output_image_assets jsonb,
 status text DEFAULT 'succeeded',output_expired_at timestamptz);
""" + cls.guard + """
CREATE TRIGGER image_retention_guard BEFORE INSERT OR UPDATE ON image_tasks
FOR EACH ROW EXECUTE FUNCTION image_retention_reference_guard();
""" + f"""
INSERT INTO image_assets VALUES (1,'generated/1/{ASSET}',NULL),(2,'generated/1/{OTHER}',NULL);
INSERT INTO image_tasks(id,input_image_url,output_image_url) VALUES(1,'{URL}','https://example.test/{OTHER}');
INSERT INTO image_tasks(id) VALUES(2);
UPDATE image_assets SET retention_pending_at=now() WHERE id=1;
"""

    def execute(self, body, *, original=False):
        setup = self.setup
        if original:
            setup = setup.replace(self.values["METADATA_ONLY_GUARD"], "", 1)
        return subprocess.run(["psql", "-X", "-v", "ON_ERROR_STOP=1", "-d", self.dsn],
            input=setup+body+"\nROLLBACK;\n", text=True, capture_output=True, timeout=15)

    def succeeds(self, body):
        result = self.execute(body)
        self.assertEqual(result.returncode, 0, result.stderr)

    def rejects(self, body):
        self.succeeds("""
DO $test$ BEGIN
  BEGIN
""" + body + """
    RAISE EXCEPTION 'expected expired-reference rejection';
  EXCEPTION WHEN check_violation THEN
    IF SQLERRM <> 'Image has expired' THEN RAISE; END IF;
  END;
END $test$;
""")

    def test_old_guard_reproduces_retention_rollback(self):
        result = self.execute("UPDATE image_tasks SET output_expired_at=now() WHERE id=1;", original=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Image has expired", result.stderr)

    def test_metadata_expiry_with_unchanged_expired_input(self):
        self.succeeds("""
UPDATE image_tasks SET output_expired_at=now() WHERE id=1;
DO $test$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM image_tasks WHERE id=1 AND output_expired_at IS NOT NULL AND status='succeeded')
 THEN RAISE EXCEPTION 'retention metadata not saved'; END IF;
END $test$;
""")

    def test_insert_expired_reference_rejected(self):
        self.rejects(f"INSERT INTO image_tasks(id,input_image_url) VALUES(3,'{URL}');")

    def test_new_input_reference_rejected(self):
        self.rejects(f"UPDATE image_tasks SET input_image_url='{URL}' WHERE id=2;")

    def test_new_input_array_reference_rejected(self):
        self.rejects(f"""UPDATE image_tasks SET input_image_urls='["{URL}"]' WHERE id=2;""")

    def test_collect_expired_output_rejected(self):
        self.succeeds(f"UPDATE image_tasks SET output_image_url='{URL}' WHERE id=2;")
        self.rejects(f"UPDATE image_tasks SET output_image_url='{URL}',is_collected=true WHERE id=2;")

    def test_feature_expired_output_rejected(self):
        self.rejects(f"UPDATE image_tasks SET output_image_url='{URL}',is_gallery_featured=true WHERE id=2;")

    def test_multi_image_collection_rejected(self):
        self.rejects(f"""UPDATE image_tasks SET output_image_assets='[{{"url":"{URL}"}}]',is_collected=true WHERE id=2;""")

    def test_new_live_reference_allowed(self):
        self.succeeds(f"UPDATE image_tasks SET input_image_url='https://example.test/{OTHER}' WHERE id=2;")

    def test_migrations_match_and_downgrade_restores_original_guard(self):
        admin = literals(ROOT / "admin-server" / MIGRATION)
        self.assertEqual(admin, self.values)
        original = self.guard.replace(self.values["METADATA_ONLY_GUARD"], "", 1)
        self.assertNotIn("Metadata-only", original)
        self.assertIn("FOR KEY SHARE", original)

if __name__ == "__main__":
    unittest.main()
