from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


def register_error_handlers(app):
    @app.exception_handler(HTTPException)
    async def handle_http_error(request, error):
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": error.detail, "request_id": request.state.request_id},
            headers=error.headers,
        )
