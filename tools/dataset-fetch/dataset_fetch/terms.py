"""ADR-0022 license gate for evaluation data.

Shipped artifacts require a permissive license, but evaluation datasets may
carry research-only or share-alike terms when they are downloaded by a script
for internal benchmarking and never redistributed (ADR-0022). This module
enforces that distinction: every WP-1.5 dataset is ``download-only``, and only
explicitly reviewed identifiers are accepted.
"""

from __future__ import annotations

from typing import Any

from .errors import LICENSE_FORBIDDEN, fail

# Download-only identifiers reviewed for internal evaluation. Adding one is a
# license decision and must be justified in the dataset's NOTICE.md.
ALLOWED_DOWNLOAD_ONLY = {
    "MIT": "permissive",
    "Apache-2.0": "permissive",
    "BSD-3-Clause": "permissive",
    "CC0-1.0": "public-domain",
    "CC-BY-4.0": "attribution",
    "CC-BY-SA-4.0": "share-alike, internal evaluation only",
    "MS-MARCO-Research": "research terms, internal evaluation only",
}

# Never acceptable, even download-only: non-commercial or missing terms make
# the evaluation evidence unpublishable.
FORBIDDEN = {
    "GPL-2.0",
    "GPL-3.0",
    "AGPL-3.0",
    "LGPL-2.1",
    "LGPL-3.0",
    "CC-BY-NC-4.0",
    "CC-BY-ND-4.0",
    "CC-BY-NC-SA-4.0",
    "UNKNOWN",
}


def check_license(manifest: dict[str, Any], *, location: str = "manifest.license") -> str:
    record = manifest["license"]
    identifier = record["id"]
    if identifier in FORBIDDEN:
        raise fail(
            LICENSE_FORBIDDEN,
            f"license {identifier!r} is forbidden for evaluation data",
            location=location,
        )
    if identifier not in ALLOWED_DOWNLOAD_ONLY:
        raise fail(
            LICENSE_FORBIDDEN,
            f"license {identifier!r} is not on the reviewed internal-evaluation allowlist",
            location=location,
        )
    if record["redistribution"] != "download-only":
        raise fail(
            LICENSE_FORBIDDEN,
            "evaluation datasets must be download-only; content is never redistributed",
            location=f"{location}.redistribution",
        )
    if not record["terms_url"].startswith(("https://", "http://")):
        raise fail(
            LICENSE_FORBIDDEN,
            "terms_url must be an immutable http(s) revision URL",
            location=f"{location}.terms_url",
        )
    return identifier
