"""Is there a newer figscribe?

Asked only when the person asks: *Help > Check for Updates…* and `figscribe
check-update` (decision 0069). One request to GitHub for the latest release,
which carries nothing about the person; nothing is downloaded or installed.
No Qt here, so the command line needs none.
"""

from __future__ import annotations

import json
import re
import ssl
from dataclasses import dataclass
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import figscribe

REPOSITORY = "https://github.com/f4ren/figscribe"
RELEASES_PAGE = f"{REPOSITORY}/releases"
LATEST = REPOSITORY.replace("github.com", "api.github.com/repos") + "/releases/latest"
TIMEOUT = 8
"""Seconds; the window waits, so not long."""

PIP_UPGRADE = "pip install --upgrade figscribe"
PIPX_UPGRADE = "pipx upgrade figscribe"

_VERSION = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?([.-]?(?:dev|a|b|rc)\.?\d*)?")


class UpdateError(Exception):
    """The question got no answer; the message says why, for a person."""


class CertificateError(UpdateError):
    """The secure connection could not be verified."""


@dataclass(frozen=True)
class Release:
    version: str
    """Without the leading v of the tag."""
    url: str
    """The release's page."""


def _key(version: str) -> tuple[int, int, int, bool] | None:
    """What versions are ordered by; the last part puts a release after its own
    pre-releases. None for text that is not a version."""
    match = _VERSION.fullmatch(version.strip())
    if match is None:
        return None
    major, minor, patch, early = match.groups()
    return int(major), int(minor), int(patch or 0), early is None


def is_newer(release: str, current: str) -> bool | None:
    """Whether `release` is a later version than `current`; None if either
    cannot be read as a version."""
    new, old = _key(release), _key(current)
    return None if new is None or old is None else new > old


def tls_context() -> ssl.SSLContext:
    """Certificates checked as the system does it, where truststore is there (it
    comes with the chat extra, so with the installers): a frozen program does not
    find the certificate files Python's own default looks for. Not injected into
    `ssl`, which the assistant's connections use too."""
    try:
        import truststore
    except ImportError:
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def latest_release() -> Release:
    """The latest release on GitHub; an `UpdateError` in words if there is no
    answer."""
    request = Request(
        LATEST,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"figscribe/{figscribe.__version__}",
        },
    )
    try:
        with urlopen(request, timeout=TIMEOUT, context=tls_context()) as answer:
            data = json.loads(answer.read())
        tag, page = data["tag_name"], data.get("html_url")
        version = tag.removeprefix("v")
    except HTTPError as exc:
        if exc.code == 404:
            raise _error("GitHub has no release of figscribe.") from exc
        if exc.code in (403, 429):
            raise _error(
                "GitHub has been asked too many times from this network; try "
                "again in an hour."
            ) from exc
        raise _error(f"GitHub answered with an error ({exc.code}).") from exc
    except (OSError, HTTPException) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise _error(
                "figscribe could not verify the secure connection to GitHub. Some "
                "Pythons, such as those from python.org on macOS, come without "
                "certificates.",
                CertificateError,
            ) from exc
        if isinstance(reason, TimeoutError):
            raise _error("GitHub did not answer in time.") from exc
        raise _error(
            "figscribe could not reach GitHub. Is the computer online?"
        ) from exc
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise _error("GitHub's answer could not be read.") from exc
    # Only a page of the project is ever opened, whatever the answer says.
    if not (isinstance(page, str) and page.startswith(f"{REPOSITORY}/")):
        page = RELEASES_PAGE
    return Release(version, page)


def _error(why: str, kind: type[UpdateError] = UpdateError) -> UpdateError:
    return kind(f"{why}\n\nThe releases are listed at {RELEASES_PAGE}")


def describe(release: Release, *, installed: bool) -> str:
    """What to tell the person about `release`. `installed`: this is the program
    of an installer, not one installed with pip."""
    current = figscribe.__version__
    newer = is_newer(release.version, current)
    if newer is False:
        return f"figscribe {current} is the newest version."
    if newer is None:
        return (
            f"The latest release is called {release.version}; you have {current}.\n"
            f"{release.url}"
        )
    found = f"figscribe {release.version} is available; you have {current}."
    if installed:
        return (
            f"{found}\n\nDownload the installer from the release page and install "
            "it over this one."
        )
    return f"{found}\n\nUpgrade with  {PIP_UPGRADE}\nor  {PIPX_UPGRADE}"
