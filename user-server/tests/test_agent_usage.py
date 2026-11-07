from app.services.agent_usage import list_usage_for_api_keys, usage_record_api_key_id, usage_record_out


class FakeUsageClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def list_user_usage(self, **kwargs):
        self.calls.append(kwargs)
        key_id = kwargs["api_key_id"]
        rows = {
            11: [
                {"id": "a", "api_key_id": 11, "api_key": {"id": 11, "name": "A"}, "created_at": "2026-07-21T10:00:00Z", "input_tokens": 2},
                {"id": "c", "api_key_id": 11, "api_key": {"id": 11, "name": "A"}, "created_at": "2026-07-21T08:00:00Z", "input_tokens": 3},
            ],
            22: [
                {"id": "b", "api_key_id": 22, "api_key": {"id": 22, "name": "B"}, "created_at": "2026-07-21T09:00:00Z", "output_tokens": 4},
            ],
        }[key_id]
        return {"items": rows, "total": len(rows), "page": kwargs["page"], "page_size": kwargs["page_size"]}


async def test_multiple_key_usage_is_merged_in_global_time_order():
    client = FakeUsageClient()

    result = await list_usage_for_api_keys(
        client,
        agent_user_id=1001,
        api_key_ids=[11, 22],
        page=1,
        page_size=2,
    )

    assert [row["id"] for row in result["items"]] == ["a", "b"]
    assert result["total"] == 3
    assert {call["api_key_id"] for call in client.calls} == {11, 22}


def test_usage_record_output_keeps_key_scope_and_member_identity():
    row = {
        "id": 9,
        "api_key_id": 22,
        "api_key": {"id": 22, "name": "成员 Key"},
        "input_tokens": 5,
        "output_tokens": 7,
        "actual_cost": "0.25",
        "created_at": "2026-07-21T10:00:00Z",
    }
    member = {"user_id": 3, "nickname": "小林"}

    assert usage_record_api_key_id(row) == 22
    output = usage_record_out(row, member=member)
    assert output["tokens"] == 12
    assert output["api_key_name"] == "成员 Key"
    assert output["member"] == member
