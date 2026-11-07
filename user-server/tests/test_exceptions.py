import json

from fastapi.exceptions import RequestValidationError

from app.core.exceptions import validation_error_response


def test_validation_error_response_uses_domain_message_and_is_json_serializable():
    error = RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", "username"),
                "msg": "Value error, 用户名不能包含空白字符",
                "input": "Mr Lemon",
                "ctx": {"error": ValueError("用户名不能包含空白字符")},
            }
        ]
    )

    response = validation_error_response(error)
    payload = json.loads(response.body)

    assert response.status_code == 422
    assert payload["code"] == 422
    assert payload["message"] == "用户名不能包含空白字符"
    assert payload["data"][0]["ctx"]["error"] == "用户名不能包含空白字符"
