from fastapi import Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """Raised by service functions when a rule refuses an operation."""

    def __init__(self, code: str, message: str, status: int = 400):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"detail": {"code": exc.code, "message": exc.message}},
    )
