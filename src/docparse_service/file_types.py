from docparse_service.schemas import FileKind

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
_OFFICE_EXTENSIONS = {
    ".docx": FileKind.DOCX,
    ".pptx": FileKind.PPTX,
    ".xlsx": FileKind.XLSX,
}
_CONTENT_TYPE_MAP = {
    "application/pdf": FileKind.PDF,
    "image/png": FileKind.IMAGE,
    "image/jpeg": FileKind.IMAGE,
    "image/tiff": FileKind.IMAGE,
    "image/bmp": FileKind.IMAGE,
    "image/webp": FileKind.IMAGE,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": FileKind.DOCX,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": FileKind.PPTX,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": FileKind.XLSX,
}


def detect_file_kind(name: str, content_type: str | None) -> FileKind:
    ext = _extension(name)
    if ext == ".pdf":
        return FileKind.PDF
    if ext in _IMAGE_EXTENSIONS:
        return FileKind.IMAGE
    if ext in _OFFICE_EXTENSIONS:
        return _OFFICE_EXTENSIONS[ext]
    if content_type:
        normalized = content_type.split(";", 1)[0].strip().lower()
        if normalized in _CONTENT_TYPE_MAP:
            return _CONTENT_TYPE_MAP[normalized]
    return FileKind.UNSUPPORTED


def is_supported(kind: FileKind) -> bool:
    return kind is not FileKind.UNSUPPORTED


def _extension(name: str) -> str:
    dot = name.rfind(".")
    if dot < 0:
        return ""
    return name[dot:].lower()
