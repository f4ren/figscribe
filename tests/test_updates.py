"""Is there a newer figscribe? The question is asked only when the person asks
(decision 0069); no test here goes online."""

from __future__ import annotations

import io
import json
import socket
import ssl
from urllib.error import HTTPError, URLError

import pytest

import figscribe
from figscribe import updates
from figscribe.cli import main

PAGE = "https://github.com/f4ren/figscribe/releases/tag/v9.0.0"


def _answers(monkeypatch, body: object = None, raises: Exception | None = None) -> list:
    """Let GitHub answer with `body` (as JSON, or bytes as they are) or fail."""
    asked = []

    def urlopen(request, timeout, context):
        asked.append((request, timeout))
        if raises is not None:
            raise raises
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        return io.BytesIO(data)

    monkeypatch.setattr(updates, "urlopen", urlopen)
    return asked


def _release(tag: str, url: str = PAGE) -> dict:
    return {"tag_name": tag, "html_url": url}


@pytest.mark.parametrize(
    ("tag", "current", "newer"),
    [
        ("v0.4.0", "0.3.0", True),
        ("v0.3.1", "0.3.0", True),
        ("v0.10.0", "0.9.0", True),
        ("v1.0", "0.9.9", True),
        ("v0.3.0", "0.3.0", False),
        ("v0.3.0", "0.4.0", False),
        ("v0.4.0", "0.4.0.dev0", True),  # the release of what is being built
        ("v0.4.0", "0.4.0rc1", True),
        ("nightly", "0.3.0", None),  # not a version: claim nothing
        ("v0.4.0", "unknown", None),
    ],
)
def test_versions_are_compared_by_their_numbers(tag, current, newer) -> None:
    assert updates.is_newer(tag, current) is newer


def test_the_latest_release_is_asked_for_without_anything_about_the_person(
    monkeypatch,
) -> None:
    asked = _answers(monkeypatch, _release("v9.0.0"))
    release = updates.latest_release()
    assert (release.version, release.url) == ("9.0.0", PAGE)
    request, timeout = asked[0]
    assert request.full_url == (
        "https://api.github.com/repos/f4ren/figscribe/releases/latest"
    )
    assert request.get_header("User-agent") == f"figscribe/{figscribe.__version__}"
    assert 0 < timeout <= 10
    assert request.data is None


def test_a_link_that_leads_elsewhere_is_not_taken(monkeypatch) -> None:
    _answers(monkeypatch, _release("v9.0.0", "https://example.com/figscribe.exe"))
    assert updates.latest_release().url == updates.RELEASES_PAGE


def _http(code: int) -> HTTPError:
    return HTTPError("url", code, "reason", None, None)


@pytest.mark.parametrize(
    ("raises", "body", "words"),
    [
        (_http(404), None, "no release"),
        (_http(403), None, "too many"),
        (_http(429), None, "too many"),
        (_http(500), None, "error (500)"),
        (URLError(socket.gaierror()), None, "online"),
        (URLError(TimeoutError()), None, "in time"),
        (TimeoutError(), None, "in time"),
        (ConnectionResetError(), None, "online"),
        (None, b"<html>", "could not be read"),
        (None, [1, 2], "could not be read"),
        (None, {"html_url": PAGE}, "could not be read"),
    ],
)
def test_every_failure_is_said_in_words_with_the_page_to_look_at(
    monkeypatch, raises, body, words
) -> None:
    _answers(monkeypatch, body, raises)
    with pytest.raises(updates.UpdateError) as caught:
        updates.latest_release()
    message = str(caught.value)
    assert words in message and updates.RELEASES_PAGE in message
    assert not isinstance(caught.value, updates.CertificateError)


@pytest.mark.parametrize(
    "raises",
    [
        URLError(ssl.SSLCertVerificationError("self-signed")),
        ssl.SSLCertVerificationError("self-signed"),
    ],
)
def test_a_certificate_that_cannot_be_checked_has_its_own_words(
    monkeypatch, raises
) -> None:
    _answers(monkeypatch, raises=raises)
    with pytest.raises(updates.CertificateError, match="could not verify"):
        updates.latest_release()


def test_the_command_says_there_is_a_newer_one(monkeypatch, capsys) -> None:
    _answers(monkeypatch, _release("v9.0.0"))
    monkeypatch.setattr("sys.argv", ["figscribe", "check-update"])
    assert main() == 0
    said = capsys.readouterr().out
    assert "9.0.0" in said and figscribe.__version__ in said
    assert "pip install --upgrade figscribe" in said


def test_the_command_says_this_one_is_the_newest(monkeypatch, capsys) -> None:
    _answers(monkeypatch, _release(f"v{figscribe.__version__}"))
    monkeypatch.setattr("sys.argv", ["figscribe", "check-update"])
    assert main() == 0
    assert "newest" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("raises", "code"),
    [
        (URLError(socket.gaierror()), 1),
        (ssl.SSLCertVerificationError("self-signed"), 3),
    ],
)
def test_the_command_tells_a_certificate_problem_apart(
    monkeypatch, capsys, raises, code
) -> None:
    """The installers' smoke test fails on the certificate, not on the network."""
    _answers(monkeypatch, raises=raises)
    monkeypatch.setattr("sys.argv", ["figscribe", "check-update"])
    assert main() == code
    assert capsys.readouterr().err.startswith("figscribe: ")


def test_the_installed_program_is_not_told_to_use_pip() -> None:
    text = updates.describe(updates.Release("9.0.0", PAGE), installed=True)
    assert "pip" not in text and "9.0.0" in text and "release page" in text
