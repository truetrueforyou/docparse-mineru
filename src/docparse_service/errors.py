from fastapi import HTTPException


def api_error(http_status: int, code: str, message: str, retryable: bool = False) -> HTTPException:
    return HTTPException(
        status_code=http_status,
        detail={
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
            }
        },
    )
