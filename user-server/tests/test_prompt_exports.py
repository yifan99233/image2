import asyncio
import base64
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from anyio import CapacityLimiter

from app.api.routes import catalog_exports as exports
from app.core.exceptions import BusinessError


def xlsx_rows(data):
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(BytesIO(data)) as workbook:
        sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        assert not sheet.findall(".//m:f", ns), "prompts must never become formulas"
        rows = []
        for row in sheet.findall("m:sheetData/m:row", ns):
            values = []
            for cell in row:
                column = 0
                for char in cell.attrib["r"]:
                    if char.isdigit():
                        break
                    column = column * 26 + ord(char) - 64
                values.extend([""] * (column - len(values)))
                values[column - 1] = "".join(cell.itertext())
            rows.append(values)
        return rows


def item(index, **kwargs):
    return exports.ExportItem(f"IMG{index}", kwargs.pop("url", f"https://cdn.test/{index}"),
                              work_type="batch_generate", group_name="【XMAS-SER-480】", **kwargs)


async def collect(items):
    return b"".join([chunk async for chunk in exports.stream_export_archive(items)])


async def test_reports_preserve_full_prompts_and_include_generation_and_download_failures(monkeypatch):
    reads = []
    def read(url):
        reads.append(url)
        if url.endswith("/3"):
            raise BusinessError("下载失败", code=50220)
        return b"image", "image/png"
    monkeypatch.setattr(exports, "read_export_image", read)
    prompt = '=HYPERLINK("https://example.invalid")\n' + "提示词" * 20000
    data = await collect([item(1, prompt=prompt), item(2, status="refunded", failure_message="生成失败", url=""),
                          item(3), item(4, status="running", url="")])
    with ZipFile(BytesIO(data)) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {"【XMAS-SER-480】/", "【XMAS-SER-480】/00001-IMG1.png", "完整汇总.xlsx", "失败汇总.xlsx", "结果统计.txt"}
        rows = xlsx_rows(archive.read("完整汇总.xlsx"))
        assert len(rows) == 5
        assert "".join(rows[1][6:]) == prompt
        assert [row[3] for row in rows[1:]] == ["成功", "失败", "失败", "未完成"]
        assert len(xlsx_rows(archive.read("失败汇总.xlsx"))) == 3
        assert archive.read("结果统计.txt").decode() == "成功 1 张，失败 2 张，未完成 1 张（本次下载快照）\n"
    assert reads == ["https://cdn.test/1", "https://cdn.test/3"]


async def test_10000_image_archive_has_500_folders_and_exactly_three_reports(monkeypatch):
    monkeypatch.setattr(exports, "read_export_image", lambda url: (url.encode(), "image/png"))
    items = [exports.ExportItem(str(i), f"https://cdn.test/{i}", prompt=f"prompt-{i}", work_type="batch_generate",
                                group_name=f"【XMAS-SER-{i // 20 + 1:03d}】") for i in range(10000)]
    data = await asyncio.wait_for(collect(items), 30)
    with ZipFile(BytesIO(data)) as archive:
        assert archive.testzip() is None
        assert len([n for n in archive.namelist() if n.endswith(".png")]) == 10000
        assert len([n for n in archive.namelist() if n.endswith("/")]) == 500
        assert len(archive.namelist()) == 10503
        assert len(xlsx_rows(archive.read("完整汇总.xlsx"))) == 10001
        assert len(xlsx_rows(archive.read("失败汇总.xlsx"))) == 1
        assert archive.read("结果统计.txt").decode() == "全部成功 10000 张\n"


async def test_stream_cap_counts_download_failures_and_all_failed_export_still_has_folder(monkeypatch):
    monkeypatch.setattr(exports.settings, "image_export_stream_max_bytes", 1)
    monkeypatch.setattr(exports, "read_export_image", lambda url: (b"xx", "image/png"))
    with ZipFile(BytesIO(await collect([item(1), item(2, status="failed", url="")]))) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == 4
        assert len(xlsx_rows(archive.read("失败汇总.xlsx"))) == 3
        assert archive.read("结果统计.txt").decode() == "成功 0 张，失败 2 张\n"


async def test_prompt_export_disconnect_releases_capacity_and_bounded_reads(monkeypatch):
    limiter = CapacityLimiter(1)
    monkeypatch.setattr(exports, "export_limiter", limiter)
    monkeypatch.setattr(exports.settings, "image_export_download_workers", 3)
    reads = []
    def read(url):
        reads.append(url)
        return b"x" * 2000000, "image/png"
    monkeypatch.setattr(exports, "read_export_image", read)
    stream = exports.stream_export_archive([item(i) for i in range(100)])
    assert await anext(stream) == b"PK\x03\x04"
    await asyncio.sleep(.15)
    assert len(reads) == 3
    await asyncio.wait_for(stream.aclose(), 3)
    assert limiter.borrowed_tokens == 0


def test_auto_keeps_original_prompt_and_does_not_fall_back_to_square():
    from app.services import image_generation as generation
    from types import SimpleNamespace
    prompt = "Print brief: portrait 2:3; 10×15cm; 300dpi."
    assert generation._generation_prompt(prompt, "auto", "auto") == prompt
    assert generation._openai_size("auto", "auto") == "auto"
    assert generation._openai_size("4k", "auto") == "auto"
    body = generation._openai_chat_completions_body(SimpleNamespace(vendor_model="gpt-image-2"), prompt, "4k", "auto")
    assert body == {"model": "gpt-image-2", "messages": [{"role": "user", "content": prompt}], "size": "auto"}


def test_auto_reaches_images_and_chat_requests_without_parsing_print_dimensions(monkeypatch):
    from app.services import image_generation as generation
    prompt = "Print brief: portrait 2:3; 10×15cm; 300dpi."
    captured = []
    def post(url, body, headers, timeout):
        captured.append((url, body))
        if url.endswith("/chat/completions"):
            return {"choices": [{"message": {"content": "![image](https://fixture.invalid/image.png)"}}]}
        return {"data": [{"b64_json": base64.b64encode(b"fixture").decode()}]}
    monkeypatch.setattr(generation, "_post_json", post)
    monkeypatch.setattr(generation, "_download_image", lambda *args, **kwargs: generation.GeneratedImage(b"fixture", "image/png", args[0]))
    for mode in ("api", "sdk"):
        config = generation.GenerationModelConfig("openai", "OpenAI", "https://fixture.invalid/v1", mode, "fixture-key", "bearer", 120, "gpt-image-2")
        generation.generate_image(config, prompt, resolution="auto", aspect_ratio="auto")
        url, body = captured[-1]
        assert body["size"] == "auto" and "width" not in body and "height" not in body
        assert (body["prompt"] if mode == "api" else body["messages"][0]["content"]) == prompt
