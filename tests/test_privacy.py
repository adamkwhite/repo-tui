"""Tests for privacy-mode masking (models.mask_name / redact_text / safe_name)."""

import pytest

from repo_tui.models import RepoOverview, mask_name, redact_text


@pytest.fixture(autouse=True)
def _reset_privacy():
    """Privacy mode is a class-level toggle; keep tests isolated."""
    original = RepoOverview.privacy_mode
    yield
    RepoOverview.privacy_mode = original


def test_mask_name_keeps_first_and_last_two():
    assert mask_name("secret-repo") == "se*******po"


def test_mask_name_short_names_fully_masked():
    # <= 4 chars have no safe middle to reveal
    assert mask_name("api") == "***"
    assert mask_name("abcd") == "****"


def test_redact_text_masks_words_preserves_punctuation():
    assert redact_text("Fix login bug!") == "*** ***** ***!"


def _repo(name="my-repo", is_private=False):
    return RepoOverview(
        name=name,
        owner="me",
        url="https://example.com",
        open_issues_count=0,
        issues=[],
        sonar_status=None,
        is_private=is_private,
    )


def test_public_repo_never_masked_even_with_privacy_on():
    RepoOverview.privacy_mode = True
    assert _repo("public-repo", is_private=False).safe_name == "public-repo"


def test_private_repo_masked_only_when_privacy_on():
    private = _repo("secret-repo", is_private=True)
    RepoOverview.privacy_mode = False
    assert private.safe_name == "secret-repo"
    RepoOverview.privacy_mode = True
    assert private.safe_name == "se*******po"
