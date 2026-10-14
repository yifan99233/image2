import json
from unittest.mock import patch

import pytest

from app.core.exceptions import BusinessError
from app.services.text_generation import _split_document_for_prompt_extraction, build_agent_plan


def test_verbatim_document_mode_uses_agent_excerpts_without_rewriting():
    first_prompt = "真实摄影，雨后的街道上穿深蓝风衣的女性站在路灯下，湿润路面倒映霓虹。"
    second_prompt = "电影级自然光下，儿童在明亮教室窗边阅读绘本，木桌上有彩色蜡笔。"
    document = f"项目资料\n\n{first_prompt}\n\n补充说明\n\n{second_prompt}"
    responses = iter(
        [
            {
                "intent": "script_to_images",
                "summary": "已识别原文提示词",
                "document_mode": "verbatim_split",
                "prompts": [],
            },
            {"prompts": [first_prompt, second_prompt]},
            {"prompts": []},
        ]
    )

    with patch(
        "app.services.text_generation._chat_completion",
        side_effect=lambda *_args, **_kwargs: json.dumps(next(responses)),
    ):
        plan = build_agent_plan(
            object(),
            user_prompt="提取文档已有提示词，保留原文后批量生成",
            document_text=document,
            max_prompts=12,
        )

    assert plan["intent"] == "script_to_images"
    assert plan["prompts"] == [first_prompt, second_prompt]


def test_verbatim_document_mode_refuses_agent_text_not_found_in_source():
    document = "这份资料只有项目说明，不含可直接使用的图片提示词。"
    responses = iter(
        [
            {
                "intent": "script_to_images",
                "summary": "已识别原文提示词",
                "document_mode": "verbatim_split",
                "prompts": [],
            },
            {"prompts": ["模型自行补写的提示词，不属于原文"]},
        ]
    )

    with patch(
        "app.services.text_generation._chat_completion",
        side_effect=lambda *_args, **_kwargs: json.dumps(next(responses)),
    ):
        plan = build_agent_plan(
            object(),
            user_prompt="只提取原文提示词，不改写",
            document_text=document,
            max_prompts=12,
        )

    assert plan["intent"] == "document_split_review"
    assert plan["prompts"] == []


def test_document_batch_intent_runs_source_extraction_when_model_omits_document_mode():
    original_prompt = "真实摄影，雨后街道上穿深蓝风衣的女性站在路灯下，湿润路面倒映霓虹。"
    responses = iter(
        [
            {
                "intent": "multi_prompts",
                "summary": "用户希望把文档拆成批量任务",
                "document_mode": "none",
                "prompts": ["复述用户请求"],
            },
            {"prompts": [original_prompt]},
            {"prompts": []},
        ]
    )

    with patch(
        "app.services.text_generation._chat_completion",
        side_effect=lambda *_args, **_kwargs: json.dumps(next(responses)),
    ):
        plan = build_agent_plan(
            object(),
            user_prompt="解析文档并拆成批量生图任务",
            document_text=original_prompt,
            max_prompts=12,
        )

    assert plan["intent"] == "script_to_images"
    assert plan["prompts"] == [original_prompt]
    assert "复述用户请求" not in plan["prompts"]


def test_document_review_intent_still_attempts_source_extraction():
    original_prompt = "真实摄影，雨后街道上穿深蓝风衣的女性站在路灯下，湿润路面倒映霓虹。"
    responses = iter(
        [
            {
                "intent": "document_split_review",
                "summary": "当前内容无法完整提取",
                "document_mode": "none",
                "prompts": [],
            },
            {"prompts": [original_prompt]},
            {"prompts": []},
        ]
    )

    with patch(
        "app.services.text_generation._chat_completion",
        side_effect=lambda *_args, **_kwargs: json.dumps(next(responses)),
    ):
        plan = build_agent_plan(
            object(),
            user_prompt="解析文档并拆成批量生图任务",
            document_text=original_prompt,
            max_prompts=12,
        )

    assert plan["intent"] == "script_to_images"
    assert plan["prompts"] == [original_prompt]


def test_document_request_uses_verbatim_extraction_when_planner_fails():
    original_prompt = "真实摄影，雨后街道上穿深蓝风衣的女性站在路灯下，湿润路面倒映霓虹。"
    responses = iter(
        [
            BusinessError("文本模型调用失败", code=50240, status_code=502),
            json.dumps({"prompts": [original_prompt]}),
            json.dumps({"prompts": []}),
        ]
    )

    def completion(*_args, **_kwargs):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    with patch(
        "app.services.text_generation._chat_completion",
        side_effect=completion,
    ):
        plan = build_agent_plan(
            object(),
            user_prompt="提取文档已有提示词，保留原文后批量生成",
            document_text=original_prompt,
            max_prompts=12,
        )

    assert plan["intent"] == "script_to_images"
    assert plan["prompts"] == [original_prompt]
    assert plan["source"] == "document_extraction"
    assert plan["notes"] == "verbatim_document_extraction"
    assert "编排模型不可用" not in plan["summary"]


def test_document_request_reports_error_when_planner_and_extractor_fail():
    with patch(
        "app.services.text_generation._chat_completion",
        side_effect=BusinessError("文本模型调用失败", code=50240, status_code=502),
    ):
        with pytest.raises(BusinessError, match="文档提取模型调用失败") as error:
            build_agent_plan(
                object(),
                user_prompt="提取文档已有提示词，保留原文后批量生成",
                document_text="真实摄影，雨后的街道。",
                max_prompts=12,
            )

    assert error.value.code == 50243


def test_document_chunking_preserves_complete_multiline_excerpts_across_boundaries():
    records = [
        f"Asset {index}\n" + "a" * 90 + "\n" + "b" * 90 + "\n" + "c" * 90
        for index in range(1, 5)
    ]
    chunks = _split_document_for_prompt_extraction(
        "\n".join(records),
        chunk_chars=400,
        overlap_chars=300,
    )

    assert all(any(record in chunk for chunk in chunks) for record in records)


def test_document_extraction_audit_recovers_omitted_source_prompt():
    prompts = [
        "真实摄影，清晨海边的渔船停靠在安静码头，薄雾覆盖海面。",
        "电影自然光，明亮厨房里一只橘猫趴在木桌上，窗外有雨滴。",
        "写实人像摄影，深蓝外套的男性在旧书店通道中阅读，暖色台灯照明。",
    ]
    responses = iter(
        [
            {
                "intent": "script_to_images",
                "summary": "已识别原文提示词",
                "document_mode": "verbatim_split",
                "prompts": [],
            },
            {"prompts": prompts[:2]},
            {"prompts": prompts[2:]},
        ]
    )

    with patch(
        "app.services.text_generation._chat_completion",
        side_effect=lambda *_args, **_kwargs: json.dumps(next(responses)),
    ):
        plan = build_agent_plan(
            object(),
            user_prompt="提取文档中的既有图片提示词并批量生成，保持原文",
            document_text="\n".join(prompts),
            max_prompts=12,
        )

    assert plan["prompts"] == prompts
