"""Local ZIP64/10k export benchmark; HTTP PNG fixtures, no paid generation.

Run from user-server with its locked Python, e.g.:
DATABASE_URL=<isolated-test-db> .venv/bin/python ../scripts/benchmark_prompt_export.py
The temporary 5 GB archive is deleted after CRC and report validation.
"""
import asyncio
import argparse
import json
import resource
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user-server"))
from app.api.routes import catalog_exports as exports


async def main():
    count = 10000
    fixture = BytesIO()
    Image.effect_noise((512, 342), 100).convert("RGB").save(fixture, "PNG", compress_level=0)
    png = fixture.getvalue()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-json", type=Path, help="Optional JSON with 10,000 prompts, such as the sample import result")
    args = parser.parse_args()
    sample = json.loads(args.prompt_json.read_text()) if args.prompt_json else None
    if sample is not None and len(sample["prompts"]) != count:
        raise ValueError("Benchmark prompt file must contain 10,000 prompts")
    items = [exports.ExportItem(str(i), f"{base_url}/{i}.png", work_type="batch_generate",
                               prompt=sample["prompts"][i] if sample else f"prompt-{i}",
                               group_name=f"【XMAS-SER-{i // 20 + 1:03d}】") for i in range(count)]
    lock = threading.Lock()
    active = peak = 0
    original_read = exports.read_export_image

    def read(url):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            return original_read(url)
        finally:
            with lock:
                active -= 1

    exports.read_export_image = read
    lag = 0
    done = False
    async def heartbeat():
        nonlocal lag
        previous = time.monotonic()
        while not done:
            await asyncio.sleep(.01)
            now = time.monotonic()
            lag = max(lag, now - previous - .01)
            previous = now
    heartbeat_task = asyncio.create_task(heartbeat())
    started = time.monotonic()
    first = None
    total = 0
    with tempfile.TemporaryFile() as file:
        async for chunk in exports.stream_export_archive(items):
            if first is None:
                first = time.monotonic() - started
            total += len(chunk)
            file.write(chunk)
        elapsed = time.monotonic() - started
        done = True
        await heartbeat_task
        file.seek(0)
        with ZipFile(file) as archive:
            assert archive.testzip() is None
            assert len([entry for entry in archive.namelist() if entry.endswith(".png")]) == count
            assert len([entry for entry in archive.namelist() if entry.endswith("/")]) == 500
            assert len(archive.namelist()) == 10503
            assert archive.read("结果统计.txt").decode() == "全部成功 10000 张\n"
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    server.shutdown()
    server.server_close()
    exports.read_export_image = original_read
    if sys.platform != "darwin":
        rss *= 1024
    print(json.dumps({"images": count, "folders": 500, "zip_bytes": total, "elapsed_seconds": round(elapsed, 2),
                      "first_byte_ms": round(first * 1000, 2), "peak_rss_mib": round(rss / 1024**2, 2),
                      "max_event_loop_lag_ms": round(lag * 1000, 2), "peak_download_workers": peak,
                      "crc_verified": True, "source": "local HTTP PNG fixture downloads; actual prompt text if available"}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
