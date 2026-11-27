# WP-0.6: malformed input and repository-safety checks.
import json

import pytest

from seeky_model_export.artifacts import (
    ArtifactError,
    ensure_external_workspace,
    load_json,
    sha256_file,
    write_json,
)


def test_workspace_inside_git_worktree_is_rejected(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    candidate = repository / "nested" / "models"
    with pytest.raises(ArtifactError, match="outside every Git worktree"):
        ensure_external_workspace(candidate)
    assert not candidate.exists()


def test_workspace_outside_git_worktree_is_created(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".git").mkdir()
    candidate = tmp_path / "external" / "models"
    assert ensure_external_workspace(candidate) == candidate.resolve()
    assert candidate.is_dir()


def test_json_round_trip_and_sha256(tmp_path):
    path = tmp_path / "manifest.json"
    write_json(path, {"revision": "abc", "count": 3})
    assert load_json(path) == {"count": 3, "revision": "abc"}
    assert sha256_file(path) == sha256_file(path)
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["revision"] == "abc"


def test_malformed_json_raises_typed_error_without_echoing_content(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text('{"secret-document-text": "', encoding="utf-8")
    with pytest.raises(ArtifactError) as error:
        load_json(path)
    assert "secret-document-text" not in str(error.value)


def test_non_finite_json_is_rejected(tmp_path):
    with pytest.raises(ArtifactError):
        write_json(tmp_path / "invalid.json", {"latency": float("nan")})
    assert not (tmp_path / "invalid.json").exists()


def test_missing_manifest_raises_typed_error(tmp_path):
    with pytest.raises(ArtifactError, match="cannot be read"):
        load_json(tmp_path / "missing.json")
