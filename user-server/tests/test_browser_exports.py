from io import BytesIO

from app.api.routes import catalog_exports
from test_batch_progress import batch_client, seed, sessions
from test_prompt_exports import xlsx_rows


async def test_browser_manifest_pages_all_statuses_with_snapshot_and_visibility(sessions, batch_client, monkeypatch):
    monkeypatch.setattr(catalog_exports, "read_export_image", lambda *_: (_ for _ in ()).throw(AssertionError("no image proxy")))
    await seed(sessions, "cdn", ["succeeded"] * 210 + ["failed", "running"], input_group_name="【XMAS-SER-480】")
    await seed(sessions, "cdn", ["succeeded"] * 2, user_id=2)
    await seed(sessions, "cdn", ["succeeded"] * 2, site_id=2)
    response = await batch_client.get("/image-tasks/browser-export/items?batch_id=cdn")
    assert response.status_code == 200
    first = response.json()["data"]
    assert first["total"] == 212 and len(first["items"]) == 200 and first["has_more"]
    assert "prompt" not in first["items"][0]
    assert first["items"][0]["url"].startswith("https://cdn.test/")
    assert first["items"][0]["folder"] == "【XMAS-SER-480】"
    await seed(sessions, "cdn", ["succeeded"], task_no="late-addition")
    second = (await batch_client.get("/image-tasks/browser-export/items", params={"batch_id": "cdn", "after_id": first["next_cursor"], "max_id": first["max_id"]})).json()["data"]
    assert second["total"] == 212 and len(second["items"]) == 12 and not second["has_more"]
    assert {item["status"] for item in second["items"]} == {"succeeded", "failed", "running"}
    assert len({item["id"] for item in first["items"] + second["items"]}) == 212
    assert (await batch_client.get("/image-tasks/browser-export/items?batch_id=missing")).status_code == 400


async def test_browser_reports_use_actual_download_results_and_preserve_prompts(sessions, batch_client, monkeypatch):
    monkeypatch.setattr(catalog_exports, "read_export_image", lambda *_: (_ for _ in ()).throw(AssertionError("no image proxy")))
    prompt = '=HYPERLINK("https://example.invalid")\n' + "完整原文" * 10000
    await seed(sessions, "report", ["succeeded", "succeeded", "failed", "running"], prompt=prompt, input_group_name="【series】")
    items = (await batch_client.get("/image-tasks/browser-export/items?batch_id=report")).json()["data"]["items"]
    results = [{"id": item["id"], "status": status, "extension": ".png" if status == "成功" else "", "error": "CDN 网络失败" if index == 1 else ""}
               for index, (item, status) in enumerate(zip(items, ["成功", "失败", "失败", "未完成"]))]
    response = await batch_client.post("/image-tasks/browser-export/reports/full", json={"batch_id": "report", "results": results})
    assert response.status_code == 200
    rows = xlsx_rows(response.content)
    assert len(rows) == 5
    assert [row[3] for row in rows[1:]] == ["成功", "失败", "失败", "未完成"]
    assert "".join(rows[1][6:]) == prompt
    assert rows[1][5] == f'【series】/{items[0]["stem"]}.png'
    failed = await batch_client.post("/image-tasks/browser-export/reports/failed", json={"batch_id": "report", "results": results})
    failed_rows = xlsx_rows(failed.content)
    assert len(failed_rows) == 3 and failed_rows[1][4] == "CDN 网络失败"
    results[2].update(status="成功", extension=".png")
    assert (await batch_client.post("/image-tasks/browser-export/reports/full", json={"batch_id": "report", "results": results})).status_code == 400


async def test_browser_reports_reject_foreign_ids_duplicates_and_invalid_extensions(sessions, batch_client):
    await seed(sessions, "foreign", ["succeeded"], user_id=2)
    await seed(sessions, "own", ["succeeded"])
    own = (await batch_client.get("/image-tasks/browser-export/items?batch_id=own")).json()["data"]["items"][0]
    result = {"id": own["id"], "status": "成功", "extension": ".png"}
    endpoint = "/image-tasks/browser-export/reports/full"
    assert (await batch_client.post(endpoint, json={"batch_id": "foreign", "results": [result]})).status_code == 403
    assert (await batch_client.post(endpoint, json={"batch_id": "own", "results": [result, result]})).status_code == 400
    assert (await batch_client.post(endpoint, json={"batch_id": "own", "results": [{**result, "extension": "../../file"}]})).status_code == 422
