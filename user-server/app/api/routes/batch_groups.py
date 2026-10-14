"""Validate grouped batch-edit inputs before any image-task debit."""
import re
import unicodedata

from app.core.exceptions import BusinessError

MAX_BATCH_GROUPS = 1000
MAX_GROUPED_INPUT_IMAGES = 10000
MAX_GROUP_OUTPUTS = 9
MAX_GROUPED_OUTPUTS = 2000
MAX_GROUP_PROMPT_CHARS = 1_000_000


def validate_batch_groups(raw_groups: object, max_input_images: int) -> list[dict]:
    if not isinstance(raw_groups, list) or not raw_groups or len(raw_groups) > MAX_BATCH_GROUPS:
        raise BusinessError(f"请提交 1–{MAX_BATCH_GROUPS} 个文件夹任务组", code=40043)
    groups = []
    seen_ids = set()
    total_outputs = total_images = total_prompt_chars = 0
    for raw in raw_groups:
        if not isinstance(raw, dict):
            raise BusinessError("任务组格式错误", code=40043)
        group_id = raw.get("group_id")
        name = raw.get("group_name")
        prompt = raw.get("prompt")
        if not isinstance(group_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", group_id) or group_id in seen_ids:
            raise BusinessError("任务组编号不能为空或重复", code=40043)
        seen_ids.add(group_id)
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
            raise BusinessError("任务组名称须为 1–255 个字符", code=40043)
        if not isinstance(prompt, str) or not prompt.strip():
            raise BusinessError(f"任务组“{name}”缺少提示词", code=40043)
        path = raw.get("group_path", name.strip())
        if not isinstance(path, str) or len(path) > 1024:
            raise BusinessError("任务组文件夹路径过长", code=40043)
        ids = raw.get("input_image_ids")
        if not isinstance(ids, list) or not ids or len(ids) > max_input_images:
            raise BusinessError(f"任务组“{name}”须包含 1–{max_input_images} 张参考图", code=40043)
        if any(type(asset_id) is not int or asset_id <= 0 for asset_id in ids) or len(set(ids)) != len(ids):
            raise BusinessError(f"任务组“{name}”包含无效或重复图片编号", code=40043)
        outputs = raw.get("output_count", 1)
        if type(outputs) is not int or not 1 <= outputs <= MAX_GROUP_OUTPUTS:
            raise BusinessError(f"每个任务组生成张数须为 1–{MAX_GROUP_OUTPUTS} 的整数", code=40043)
        total_outputs += outputs
        total_images += len(ids)
        total_prompt_chars += len(prompt)
        if total_outputs > MAX_GROUPED_OUTPUTS or total_images > MAX_GROUPED_INPUT_IMAGES or total_prompt_chars > MAX_GROUP_PROMPT_CHARS:
            raise BusinessError(f"单批最多生成 {MAX_GROUPED_OUTPUTS} 张图、接收 {MAX_GROUPED_INPUT_IMAGES} 张参考图，请拆分提交", code=40043)
        groups.append({"group_id": group_id, "group_name": unicodedata.normalize("NFC", name.strip()), "group_path": path.strip(), "prompt": prompt.strip(), "input_image_ids": ids, "output_count": outputs})
    return groups
