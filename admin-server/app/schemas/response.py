from typing import Generic, TypeVar

from decimal import Decimal
from pydantic import BaseModel, field_serializer

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int
    message: str
    data: T | None = None

    @field_serializer("data", when_used="json")
    def numeric_data(self, value):
        # Keep existing JSON-number contracts; accounting stays Decimal internally.
        def numbers(item):
            if isinstance(item, Decimal):
                return int(item) if item == item.to_integral_value() else float(item)
            if isinstance(item, BaseModel):
                return numbers(item.model_dump(mode="python"))
            if isinstance(item, dict):
                return {key: numbers(val) for key, val in item.items()}
            if isinstance(item, (list, tuple)):
                return [numbers(val) for val in item]
            return item
        return numbers(value)

    @classmethod
    def ok(cls, data: T | None = None, message: str = "ok") -> "ApiResponse[T]":
        return cls(code=0, message=message, data=data)

