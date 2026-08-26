from __future__ import annotations


class SopError(ValueError):
    """A known contract or input failure with a stable machine code."""

    def __init__(self, code: str, message: str, *, details: dict | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details or {}
