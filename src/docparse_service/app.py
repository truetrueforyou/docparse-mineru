import mimetypes
from pathlib import PurePosixPath

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from docparse_service.config import Settings, get_settings
from docparse_service.db import make_session_factory
from docparse_service.errors import api_error
from docparse_service.schemas import DeviceMode, OcrMode
from docparse_service.service import ParseService


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    session_factory = make_session_factory(resolved_settings.database_url)
    service = ParseService(resolved_settings, session_factory)

    app = FastAPI(title="Docparse MinerU 3.4 Service", version="0.1.0")

    def get_service() -> ParseService:
        return service

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "HTTP_ERROR",
                    "message": str(exc.detail),
                    "retryable": False,
                }
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(_, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": str(exc), "retryable": False}},
        )

    @app.get("/v1/health")
    def health() -> dict:
        return {"status": "ok", "storage": resolved_settings.storage_backend}

    @app.post("/v1/files/parse", status_code=202)
    async def parse_file(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        ocr: OcrMode = Form(default=OcrMode.AUTO),
        device: DeviceMode | None = Form(default=None),
        parse_service: ParseService = Depends(get_service),
    ) -> dict:
        content = await file.read()
        try:
            task = parse_service.create_task(
                filename=file.filename or "upload.bin",
                content_type=file.content_type or "application/octet-stream",
                content=content,
            )
        except ValueError as exc:
            code = str(exc)
            if code == "FILE_TOO_LARGE":
                raise api_error(413, code, "File exceeds configured size limit") from exc
            if code == "INVALID_FILENAME":
                raise api_error(400, code, "Upload filename is invalid") from exc
            raise api_error(400, "UNSUPPORTED_FILE_TYPE", "File type is not supported in V1") from exc

        if resolved_settings.run_tasks_inline:
            parse_service.run_task(task.task_id, ocr, device)
        else:
            background_tasks.add_task(parse_service.run_task, task.task_id, ocr, device)

        return {"task_id": task.task_id, "file_id": task.file_id, "status": task.status}

    @app.get("/v1/tasks/{task_id}")
    def task_status(task_id: str, parse_service: ParseService = Depends(get_service)) -> dict:
        task = parse_service.get_task(task_id)
        if task is None:
            raise api_error(404, "TASK_NOT_FOUND", "Task not found")
        return {
            "task_id": task.task_id,
            "file_id": task.file_id,
            "file_name": task.file_name,
            "file_type": task.file_type,
            "engine": task.engine,
            "status": task.status,
            "error": {"code": task.error_code, "message": task.error_message}
            if task.error_code
            else None,
        }

    @app.get("/v1/tasks/{task_id}/result")
    def task_result(task_id: str, parse_service: ParseService = Depends(get_service)) -> dict:
        try:
            return parse_service.get_result(task_id)
        except KeyError as exc:
            raise api_error(404, "RESULT_NOT_FOUND", "Result not found") from exc

    @app.get("/v1/tasks/{task_id}/markdown")
    def task_markdown(task_id: str, parse_service: ParseService = Depends(get_service)) -> PlainTextResponse:
        try:
            return PlainTextResponse(parse_service.get_markdown(task_id), media_type="text/markdown")
        except KeyError as exc:
            raise api_error(404, "RESULT_NOT_FOUND", "Markdown result not found") from exc

    @app.get("/v1/tasks/{task_id}/content-list")
    def task_content_list(task_id: str, parse_service: ParseService = Depends(get_service)) -> Response:
        try:
            return Response(parse_service.get_content_list(task_id), media_type="application/json")
        except KeyError as exc:
            raise api_error(404, "RESULT_NOT_FOUND", "Content list result not found") from exc

    @app.get("/v1/tasks/{task_id}/middle")
    def task_middle(task_id: str, parse_service: ParseService = Depends(get_service)) -> Response:
        try:
            return Response(parse_service.get_middle(task_id), media_type="application/json")
        except KeyError as exc:
            raise api_error(404, "RESULT_NOT_FOUND", "Middle result not found") from exc

    @app.get("/v1/tasks/{task_id}/assets/{asset_path:path}")
    def task_asset(
        task_id: str,
        asset_path: str,
        parse_service: ParseService = Depends(get_service),
    ) -> Response:
        normalized = PurePosixPath(asset_path)
        if ".." in normalized.parts or normalized.is_absolute():
            raise api_error(400, "INVALID_ASSET_PATH", "Asset path must stay under result/images/")
        expected_prefix = f"tasks/{task_id}/result/images/"
        candidate = f"{expected_prefix}{normalized.as_posix().lstrip('/')}"
        if not candidate.startswith(expected_prefix):
            raise api_error(400, "INVALID_ASSET_PATH", "Asset path must stay under result/images/")
        try:
            data = parse_service.get_asset(task_id, normalized.as_posix())
        except KeyError as exc:
            raise api_error(404, "RESULT_NOT_FOUND", "Asset not found") from exc
        except ValueError as exc:
            raise api_error(400, "INVALID_ASSET_PATH", "Asset path must stay under result/images/") from exc
        except FileNotFoundError as exc:
            raise api_error(404, "RESULT_NOT_FOUND", "Asset not found") from exc
        mime, _ = mimetypes.guess_type(normalized.name)
        return Response(data, media_type=mime or "application/octet-stream")

    return app


app = create_app()
