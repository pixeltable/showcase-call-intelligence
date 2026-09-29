"""Check a response against the shared contract (shared/call_center_api/schemas.py)."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter, ValidationError


def conforms(model: Any, value: Any) -> tuple[bool, str]:
    """Whether value validates as model, and the first error if it does not."""
    try:
        TypeAdapter(model).validate_python(value)
        return True, ""
    except ValidationError as exc:
        error = exc.errors()[0]
        return False, f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}"
