"""Shared test set-up. The post-run seal state (P11) is read from the repository's git tags,
so no test may depend on the real repository's, before or after the real ``conf-run-v1``:
``splits._post_run`` returns False in every test unless the test requests
``real_post_run``."""

from __future__ import annotations

import pytest

from nhs_ae.evaluate import splits


@pytest.fixture(autouse=True)
def _no_post_run(request, monkeypatch):
    """``splits._post_run`` returns False, as before ``conf-run-v1``, whatever the real
    repository's tags say; a test that requests ``real_post_run`` keeps the real seam."""
    if "real_post_run" not in request.fixturenames:
        monkeypatch.setattr(splits, "_post_run", lambda: False)


@pytest.fixture
def real_post_run():
    """Opt out of ``_no_post_run``: ``splits._post_run`` runs for real, so point
    ``splits.PROJECT_ROOT`` (and ``UNSEAL_LOG``) at a temporary repository first. Returns the
    seam."""
    return splits._post_run
