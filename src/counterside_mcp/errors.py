"""Domain errors, mapped to MCP tool errors at the server boundary."""


class DomainError(Exception):
    """A caller-facing failure with a short, actionable message."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
