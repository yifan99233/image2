import asyncio
import csv
import io
import re
import urllib.parse
import urllib.request
import zipfile
import threading
import tempfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from anyio import CapacityLimiter, to_thread

from app.core.config import settings
from app.core.exceptions import BusinessError

export_limiter = CapacityLimiter(settings.image_export_max_concurrency)


@dataclass(frozen=True)
class ExportItem:
    task_no: str
    url: str
    prompt: str = ""
    source: str = ""
    batch_id: str = ""
    group_id: str = ""
    group_name: str = ""
    group_path: str = ""
    work_type: str = ""
    status: str = "succeeded"
    failure_message: str = ""


ExportInput = ExportItem | tuple[str, str]


def _normalize_export_item(value: ExportInput) -> ExportItem:
    """Accept the pre-batch tuple shape for callers/tests kept on the old API."""
    if isinstance(value, ExportItem):
        return value
    task_no, url = value
    return ExportItem(task_no=str(task_no), url=str(url))


def _safe_filename_part(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^\w\-\u4e00-\u9fff]+", "-", value.strip(), flags=re.UNICODE).strip("-._")
    return normalized[:48] or fallback


def _source_filename_part(value: str) -> str:
    if not value:
        return ""
    path_stem = Path(urllib.parse.urlparse(value).path).stem
    return _safe_filename_part(path_stem, fallback="source")


def _batch_filename_part(value: str) -> str:
    if not value:
        return "batch"
    normalized = _safe_filename_part(value, fallback="batch")
    return normalized[:16]


def _build_export_archive(items: list[ExportInput]) -> BytesIO:
    archive = BytesIO()
    total_content_bytes = 0
    max_export_bytes = max(1, int(settings.image_export_max_bytes))
    try:
        legacy_flat_archive = bool(items) and all(not isinstance(item, ExportItem) for item in items)
        with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            manifest = io.StringIO()
            manifest_writer = csv.writer(manifest)
            manifest_writer.writerow(["批次", "商品组", "输入素材", "文件", "任务编号", "提示词", "状态", "错误", "原任务组名称", "任务组编号", "文件夹路径"])
            source_groups: dict[tuple[str, str], str] = {}
            exported_count = 0
            for index, raw_item in enumerate(items, start=1):
                item = _normalize_export_item(raw_item)
                batch_folder = _batch_filename_part(item.batch_id)
                source_slug = _source_filename_part(item.source)
                try:
                    content, content_type = read_export_image(item.url)
                except BusinessError as error:
                    # A stale CDN/object must not discard the other valid files.
                    manifest_writer.writerow([batch_folder, "", source_slug, "", item.task_no, item.prompt, "失败", str(error), item.group_name, item.group_id, item.group_path])
                    continue
                total_content_bytes += len(content)
                if total_content_bytes > max_export_bytes:
                    raise BusinessError(
                        f"导出文件总大小超过限制，最大允许 {max_export_bytes // (1024 * 1024)}MB",
                        code=50237,
                        status_code=413,
                    )
                extension = export_file_extension(item.url, content_type)
                prompt_slug = _safe_filename_part(item.prompt, fallback="result")
                task_slug = _safe_filename_part(item.task_no, fallback=f"task-{index:03d}")
                group_key = (item.batch_id or "", item.group_id or item.source or "__generated__")
                if group_key not in source_groups:
                    ordinal = len([key for key in source_groups if key[0] == item.batch_id]) + 1
                    source_groups[group_key] = (
                        f"{ordinal:02d}-{_safe_filename_part(item.group_name, fallback='任务组')}" if item.group_id
                        else "生成结果" if not item.source else f"商品-{ordinal:02d}"
                    )
                group_folder = source_groups[group_key]
                relative_name = (
                    f"{index:03d}-{task_slug}{extension}"
                    if legacy_flat_archive
                    else f"{batch_folder}/{group_folder}/{index:03d}-{prompt_slug}-{task_slug}{extension}"
                )
                zip_file.writestr(relative_name, content)
                manifest_writer.writerow([batch_folder, group_folder, source_slug, relative_name, item.task_no, item.prompt, "成功", "", item.group_name, item.group_id, item.group_path])
                exported_count += 1
            if not exported_count:
                raise BusinessError("没有可用的结果图片可导出", code=50220, status_code=502)
            if not legacy_flat_archive:
                zip_file.writestr("manifest.csv", "\ufeff" + manifest.getvalue())
        archive.seek(0)
        return archive
    except BaseException:
        archive.close()
        raise


async def build_export_archive(items: list[ExportInput]) -> BytesIO:
    # Keep slow downloads/compression off the API event loop. AnyIO retains
    # the capacity slot until the worker finishes, including cancellation.
    return await to_thread.run_sync(_build_export_archive, items, limiter=export_limiter)


class _ExportCancelled(Exception):
    pass


class _StreamingZipSink:
    """Non-seekable ZIP target with bounded backpressure to the HTTP stream."""
    def __init__(self, loop, queue, stopped):
        self.loop, self.queue, self.stopped = loop, queue, stopped
        self.position = 0
        self.prefix_remaining = 4

    def tell(self):
        return self.position

    def flush(self):
        pass

    def write(self, data):
        size = len(data)
        self.position += size
        # The response already sent the first four bytes of this local ZIP
        # header so the browser can register the download before queueing.
        if self.prefix_remaining:
            skipped = min(self.prefix_remaining, size)
            if self.position == size and not data.startswith(b"PK\x03\x04"):
                raise RuntimeError("Unexpected ZIP header")
            data = data[skipped:]
            self.prefix_remaining -= skipped
        for offset in range(0, len(data), 64 * 1024):
            if self.stopped.is_set():
                raise _ExportCancelled()
            future = asyncio.run_coroutine_threadsafe(self.queue.put(data[offset:offset + 64 * 1024]), self.loop)
            while True:
                try:
                    future.result(timeout=0.1)
                    break
                except FutureTimeout:
                    if self.stopped.is_set():
                        future.cancel()
                        raise _ExportCancelled()
        return size


def _write_streaming_export(items, loop, queue, stopped):
    if items and all(isinstance(item, ExportItem) and item.work_type == "batch_generate" for item in items):
        return _write_prompt_export(items, loop, queue, stopped)
    sink = _StreamingZipSink(loop, queue, stopped)
    max_bytes = max(1, int(settings.image_export_max_bytes))
    workers = settings.image_export_download_workers
    normalized = [_normalize_export_item(item) for item in items]
    manifest = io.StringIO()
    writer = csv.writer(manifest)
    writer.writerow(["批次", "商品组", "输入素材", "文件", "任务编号", "提示词", "状态", "错误", "原任务组名称", "任务组编号", "文件夹路径"])
    groups = {}
    total = 0
    exceeded = False
    try:
        # Keep the export slot until in-flight reads finish, even if the
        # browser disconnects. Both prefetch and buffered ZIP chunks are bounded.
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="zip-image") as pool:
            futures = {i: pool.submit(read_export_image, item.url) for i, item in enumerate(normalized[:workers])}
            with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                archive.writestr("下载说明.txt", "图片按批次和任务组整理。manifest.csv 记录提示词、任务编号和每张图片的下载状态；无法获取或超过大小限制的图片会在清单中注明。\n")
                for i, item in enumerate(normalized):
                    if stopped.is_set():
                        raise _ExportCancelled()
                    batch = _batch_filename_part(item.batch_id)
                    source = _source_filename_part(item.source)
                    error = "导出总大小已达到限制，未打包此图片" if exceeded else ""
                    content = None
                    content_type = None
                    if not exceeded:
                        try:
                            content, content_type = futures.pop(i).result()
                            if total + len(content) > max_bytes:
                                exceeded = True
                                error = "导出总大小已达到限制，未打包此图片"
                        except Exception as exc:
                            error = str(exc)
                        if not exceeded and i + workers < len(normalized):
                            futures[i + workers] = pool.submit(read_export_image, normalized[i + workers].url)
                    if error:
                        writer.writerow([batch, "", source, "", item.task_no, item.prompt, "失败", error, item.group_name, item.group_id, item.group_path])
                        continue
                    total += len(content)
                    key = (item.batch_id, item.group_id or item.source or "__generated__")
                    if key not in groups:
                        ordinal = sum(1 for existing in groups if existing[0] == item.batch_id) + 1
                        groups[key] = f"{ordinal:02d}-{_safe_filename_part(item.group_name, fallback='任务组')}" if item.group_id else "生成结果" if not item.source else f"商品-{ordinal:02d}"
                    folder = groups[key]
                    name = f"{batch}/{folder}/{i + 1:03d}-{_safe_filename_part(item.prompt, fallback='result')}-{_safe_filename_part(item.task_no, fallback='task')}{export_file_extension(item.url, content_type)}"
                    with archive.open(name, "w", force_zip64=True) as output:
                        for offset in range(0, len(content), 64 * 1024):
                            output.write(content[offset:offset + 64 * 1024])
                    writer.writerow([batch, folder, source, name, item.task_no, item.prompt, "成功", "", item.group_name, item.group_id, item.group_path])
                archive.writestr("manifest.csv", "\ufeff" + manifest.getvalue())
    except _ExportCancelled:
        pass


def _write_prompt_export(items, loop, queue, stopped):
    from app.services.batch_export_reports import BatchExportReports, validate_folder_name
    sink = _StreamingZipSink(loop, queue, stopped)
    workers = settings.image_export_download_workers
    total = 0
    folders = set()
    max_bytes = settings.image_export_stream_max_bytes
    with tempfile.TemporaryDirectory(prefix="prompt-export-") as directory:
        reports = BatchExportReports(directory, max(1, max((len(item.prompt) + 29999) // 30000 for item in items)))
        try:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="prompt-zip") as pool:
                futures = {}

                def schedule(index):
                    if index < len(items) and items[index].status == "succeeded" and items[index].url:
                        futures[index] = pool.submit(read_export_image, items[index].url)

                for index in range(min(workers, len(items))):
                    schedule(index)
                with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                    for index, item in enumerate(items):
                        if stopped.is_set():
                            raise _ExportCancelled()
                        folder = item.group_name or "生成结果"
                        try:
                            validate_folder_name(folder)
                        except BusinessError:
                            folder = _safe_filename_part(folder, fallback="生成结果")
                        if folder not in folders:
                            archive.writestr(folder + "/", b"")
                            folders.add(folder)
                        name, error, content = "", "", None
                        status = "成功"
                        future = futures.pop(index, None)
                        if item.status in ("pending", "queued", "running"):
                            status, error = "未完成", "任务尚未完成，请完成后重新下载"
                        elif item.status != "succeeded":
                            status, error = "失败", item.failure_message or "生成失败"
                        elif not item.url:
                            status, error = "失败", "任务没有可用的结果图片"
                        else:
                            try:
                                content, content_type = future.result()
                                if total + len(content) > max_bytes:
                                    status, error = "失败", "导出总大小已达到限制，未打包此图片"
                            except Exception as exc:
                                status, error = "失败", str(exc)
                        if status == "成功":
                            name = f"{folder}/{index + 1:05d}-{_safe_filename_part(item.task_no, fallback='task')}{export_file_extension(item.url, content_type)}"
                            with archive.open(name, "w", force_zip64=True) as output:
                                for offset in range(0, len(content), 64 * 1024):
                                    output.write(content[offset:offset + 64 * 1024])
                            total += len(content)
                        reports.append(index + 1, item, folder, name, status, error)
                        # Release this result before scheduling the next read.
                        content = future = None
                        schedule(index + workers)
                    reports.close()
                    reports.write_to(archive)
        except _ExportCancelled:
            pass
        finally:
            for future in futures.values():
                future.cancel()
            # close() is idempotent at our boundary, including cancellation.
            if reports.books and not reports.books[0][0].fileclosed:
                reports.close()


async def stream_export_archive(items: list[ExportInput]):
    queue = asyncio.Queue(maxsize=8)
    stopped = threading.Event()
    loop = asyncio.get_running_loop()
    async def produce():
        try:
            await to_thread.run_sync(_write_streaming_export, items, loop, queue, stopped, limiter=export_limiter)
        finally:
            while not stopped.is_set():
                try:
                    await asyncio.wait_for(queue.put(None), timeout=0.1)
                    break
                except TimeoutError:
                    continue
    producer = asyncio.create_task(produce())
    try:
        yield b"PK\x03\x04"
        while True:
            chunk = await queue.get()
            if chunk is None:
                await producer
                break
            yield chunk
    finally:
        stopped.set()
        try:
            await asyncio.shield(producer)
        except asyncio.CancelledError:
            # The producer keeps its capacity slot while its bounded reads
            # exit. Consume its eventual exception without holding the client.
            producer.add_done_callback(lambda task: None if task.cancelled() else task.exception())


def export_file_extension(url: str, content_type: str | None) -> str:
    mime_extension = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "video/x-m4v": ".m4v",
    }.get((content_type or "").split(";")[0].strip().lower())
    if mime_extension:
        return mime_extension
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm", ".mov", ".m4v"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".png"


def read_export_image(url: str) -> tuple[bytes, str | None]:
    if url.startswith("/"):
        raise BusinessError("图片地址必须是 MinIO 公开地址", code=40031)

    max_bytes = max(1, int(settings.image_result_download_max_bytes))
    parsed = urllib.parse.urlparse(url)
    candidates = [url]
    public_endpoint = settings.minio_public_endpoint.rstrip("/")
    if parsed.path.startswith("/image2-assets/") and public_endpoint:
        fallback = urllib.parse.urlunsplit(
            (
                urllib.parse.urlparse(public_endpoint).scheme,
                urllib.parse.urlparse(public_endpoint).netloc,
                parsed.path,
                parsed.query,
                "",
            )
        )
        if fallback and fallback not in candidates:
            candidates.append(fallback)

    last_error: Exception | None = None
    for candidate in candidates:
        request = urllib.request.Request(candidate, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content_type = response.headers.get("Content-Type")
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            raise BusinessError(
                                f"导出文件过大，单个文件最大允许 {max_bytes // (1024 * 1024)}MB",
                                code=50234,
                                status_code=413,
                            )
                    except ValueError:
                        pass
                chunks: list[bytes] = []
                received = 0
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > max_bytes:
                        raise BusinessError(
                            f"导出文件过大，单个文件最大允许 {max_bytes // (1024 * 1024)}MB",
                            code=50234,
                            status_code=413,
                        )
                    chunks.append(chunk)
                return b"".join(chunks), content_type
        except BusinessError:
            raise
        except Exception as exc:
            last_error = exc

    raise BusinessError(f"导出图片下载失败：{last_error}", code=50220, status_code=502) from last_error
