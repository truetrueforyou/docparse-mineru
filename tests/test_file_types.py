from docparse_service.file_types import FileKind, detect_file_kind, is_supported


def test_pdf_and_docx_supported():
    assert is_supported(detect_file_kind("a.pdf", "application/pdf"))
    assert is_supported(detect_file_kind("a.docx", None))


def test_epub_unsupported():
    assert not is_supported(detect_file_kind("a.epub", None))
