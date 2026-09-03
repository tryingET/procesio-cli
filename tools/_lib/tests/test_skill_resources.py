from __future__ import annotations

from pathlib import Path

import pytest

from tools._lib.skill_resources import (
    SkillResourceError,
    SkillResourceNotFound,
    SkillResourceNotText,
    read_text_resource,
    resource_index,
)


def test_index_lists_metadata_without_loading_contents(tmp_path):
    root = tmp_path / "skill"
    (root / "references").mkdir(parents=True)
    (root / "references" / "guide.md").write_text("hello", encoding="utf-8")
    index = resource_index(root)
    assert index["references"] == ["references/guide.md"]
    assert index["resources"][0]["size"] == 5
    assert index["resources"][0]["media_type"] == "text/markdown"


def test_read_text_resource_returns_content_and_metadata(tmp_path):
    root = tmp_path / "skill"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "check.py").write_text("print('ok')\n", encoding="utf-8")
    item = read_text_resource(root, "scripts/check.py")
    assert item["content"] == "print('ok')\n"
    assert item["category"] == "scripts"


@pytest.mark.parametrize("path", ["../secret", "references/../../secret", "/etc/passwd", "SKILL.md"])
def test_traversal_and_non_resource_paths_are_rejected(tmp_path, path):
    with pytest.raises(SkillResourceError):
        read_text_resource(tmp_path, path)


def test_missing_resource_has_specific_error(tmp_path):
    with pytest.raises(SkillResourceNotFound):
        read_text_resource(tmp_path, "references/missing.md")


def test_binary_resource_is_not_decoded_as_text(tmp_path):
    root = tmp_path / "skill"
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "image.bin").write_bytes(b"\xff\xfe")
    with pytest.raises(SkillResourceNotText):
        read_text_resource(root, "assets/image.bin")


def test_symlink_escape_is_rejected_when_supported(tmp_path):
    root = tmp_path / "skill"
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (root / "references").mkdir(parents=True)
    link = root / "references" / "outside.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(SkillResourceError):
        read_text_resource(root, "references/outside.md")
