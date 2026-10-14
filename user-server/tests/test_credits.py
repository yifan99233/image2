async def test_credit_balance_requires_auth(client):
    response = await client.get("/credits/balance")

    assert response.status_code == 401


async def test_credit_balance_created_for_registered_user(client):
    register_response = await client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "strong-pass-123"},
    )
    token = register_response.json()["data"]["access_token"]

    response = await client.get("/credits/balance", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["data"] == {
        "balance": 0,
        "gift_balance": 0,
        "total_gifted": 0,
        "total_recharged": 0,
        "total_consumed": 0,
    }
