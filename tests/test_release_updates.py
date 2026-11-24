# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

from io import BytesIO
import json
import ssl
from urllib.error import HTTPError, URLError

import pytest

from backend import release_updates as updates


@pytest.mark.parametrize("tag,draft,pre,expected", [
    ("v2.0.1", False, False, "v2.0.1"), ("v2.0.1", True, False, None),
    ("v2.0.1", False, True, None), ("v2.0.2-rc1", False, False, None),
    ("v2.0.1/../bad", False, False, None),
])
def test_only_official_versions(monkeypatch, tag, draft, pre, expected):
    payload = json.dumps(dict(tag_name=tag, draft=draft, prerelease=pre)).encode()
    monkeypatch.setattr(updates, "urlopen", lambda request, timeout: BytesIO(payload))
    assert updates.latest_tag() == expected


def test_no_release(monkeypatch, tmp_path):
    def empty(request, timeout):
        raise HTTPError(request.full_url, 404, "No release", {}, None)
    monkeypatch.setattr(updates, "urlopen", empty)
    status = updates.release_status(tmp_path, refresh=True)
    assert (status["state"], status["latest"], status["available"]) == ("checked", None, False)


def test_cache_and_offline(monkeypatch, tmp_path):
    now = [100]
    calls = []
    def fetch():
        calls.append(1)
        if len(calls) > 1:
            raise TimeoutError()
        return "v2.10.0"
    monkeypatch.setattr(updates, "__version__", "2.9.9")
    monkeypatch.setattr(updates, "latest_tag", fetch)
    monkeypatch.setattr(updates.time, "time", lambda: now[0])
    assert updates.release_status(tmp_path)["state"] == "unchecked"
    assert not list(tmp_path.iterdir())
    fresh = updates.release_status(tmp_path, refresh=True)
    assert fresh["available"] and fresh["url"].endswith("/releases/tag/v2.10.0")
    now[0] += 60
    assert updates.release_status(tmp_path, refresh=True) == fresh
    offline = updates.release_status(tmp_path, refresh=True, manual=True)
    assert offline["state"] == "offline" and offline["url"] == fresh["url"]
    assert updates.release_status(tmp_path) == offline
    assert len(calls) == 2
    monkeypatch.setattr(updates, "__version__", "2.10.0")
    assert not updates.release_status(tmp_path)["available"]


@pytest.mark.parametrize("failure", [
    FileNotFoundError("TLS policy file missing"),
    URLError(ssl.SSLCertVerificationError("untrusted issuer")),
])
def test_manual_retry_after_tls_failure(monkeypatch, tmp_path, failure):
    results = iter([failure, "v2.0.0"])
    def fetch():
        value = next(results)
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(updates, "latest_tag", fetch)
    assert updates.release_status(tmp_path, refresh=True)["state"] == "tls_error"
    assert updates.release_status(tmp_path, refresh=True)["state"] == "tls_error"
    assert updates.release_status(tmp_path, refresh=True, manual=True)["latest"] == "2.0.0"


def test_cache_failure_is_local(tmp_path):
    (tmp_path / "release-check.sqlite").mkdir()
    assert updates.release_status(tmp_path, refresh=True)["state"] == "cache_error"
