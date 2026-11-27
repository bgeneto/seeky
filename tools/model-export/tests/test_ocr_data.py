# WP-0.6: OCR render input normalization without font or image hardware.
import pytest

from seeky_model_export.ocr_data import OcrDataError, normalized_paragraphs


def test_normalized_paragraphs_join_hard_wrapped_public_text():
    body = "First line of a sufficiently long paragraph, continued here,\nand it reaches the required body length for rendering exactly."
    body += "\n\nShort ignored.\n\nSecond paragraph has enough words to count. " * 2
    paragraphs = normalized_paragraphs(body)
    assert paragraphs[0] == (
        "First line of a sufficiently long paragraph, continued here, "
        "and it reaches the required body length for rendering exactly."
    )
    assert all("  " not in paragraph and "\n" not in paragraph for paragraph in paragraphs)


def test_normalized_paragraphs_reject_text_without_body_paragraphs():
    with pytest.raises(OcrDataError):
        normalized_paragraphs("Title\n\nToo short.\n")
