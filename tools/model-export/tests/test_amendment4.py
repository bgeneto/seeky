# WP-0.6 preregistration amendment 4: PP-OCRv6 tiny replaces the PP-OCRv5
# mobile OCR proxy. Its recipe and dictionary come from the vendor's own
# inference.yml, never from hardcoded values (P8), and are checked on load.
import pytest
import yaml

from seeky_model_export import ocr_run

DET_YML = """
PostProcess:
  box_thresh: 0.4
  max_candidates: 3000
  name: DBPostProcess
  thresh: 0.2
  unclip_ratio: 1.4
PreProcess:
  transform_ops:
  - DecodeImage:
      img_mode: BGR
  - DetResizeForTest: null
  - NormalizeImage:
      mean:
      - 0.485
      - 0.456
      - 0.406
      scale: 1./255.
      std:
      - 0.229
      - 0.224
      - 0.225
"""

REC_YML = """
PostProcess:
  name: CTCLabelDecode
  character_dict:
  - '!'
  - '~'
  - '1'
  - 'on'
  - ã
  - ç
"""


def _load(text):
    return yaml.load(text, Loader=yaml.BaseLoader)


def test_detector_recipe_is_read_from_the_vendor_config():
    mean, std, postprocess = ocr_run.det_recipe(_load(DET_YML))
    assert mean == (0.485, 0.456, 0.406)
    assert std == (0.229, 0.224, 0.225)
    assert dict(postprocess) == {
        "thresh": 0.2,
        "box_thresh": 0.4,
        "unclip_ratio": 1.4,
        "max_candidates": 3000.0,
    }


def test_detector_config_without_normalization_is_a_typed_error():
    config = _load(DET_YML)
    config["PreProcess"]["transform_ops"] = [{"DecodeImage": {"img_mode": "BGR"}}]
    with pytest.raises(ocr_run.OcrRunError):
        ocr_run.det_recipe(config)


def test_dictionary_entries_stay_literal_characters():
    assert ocr_run.rec_characters(_load(REC_YML)) == ["!", "~", "1", "on", "ã", "ç"]


def test_missing_or_empty_dictionary_is_a_typed_error():
    with pytest.raises(ocr_run.OcrRunError):
        ocr_run.rec_characters({"PostProcess": {}})
    with pytest.raises(ocr_run.OcrRunError):
        ocr_run.rec_characters({"PostProcess": {"character_dict": []}})


def test_recognizer_classes_must_match_dictionary_plus_blank_and_space():
    characters = ["a", "b", "c"]
    ocr_run.check_dictionary(5, characters)
    ocr_run.check_dictionary("classes", characters)  # symbolic dimension: unknown
    with pytest.raises(ocr_run.OcrRunError):
        ocr_run.check_dictionary(4, characters)


def test_ocr_proxy_is_pinned_by_revision_and_hash():
    assert ocr_run.OCR_SLUG == "ppocrv6-tiny"
    for repository, revision, sha256 in ocr_run.OCR_GRAPHS.values():
        assert repository.startswith("PaddlePaddle/PP-OCRv6_tiny_")
        assert len(revision) == 40 and len(sha256) == 64
