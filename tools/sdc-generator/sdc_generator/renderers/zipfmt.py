"""Deterministic ZIP container with fixed metadata (SPEC-0004 section 5.1)."""

from __future__ import annotations

import io
import zipfile

_FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def build_zip(entries: list[tuple[str, bytes]], *, mimetype: str | None = None) -> bytes:
    """Return a byte-identical ZIP for the same entries.

    Entries are stored (not deflated), sorted by name, with a fixed timestamp,
    fixed Unix creator/permissions, and no host metadata. Storing avoids
    zlib-version-dependent deflate output, so the archive is identical on every
    CI operating system.
    """

    buffer = io.BytesIO()
    ordered = sorted(entries, key=lambda entry: entry[0])
    if mimetype is not None:
        found = [entry for entry in ordered if entry[0] == "mimetype"]
        if len(found) != 1:
            raise ValueError("mimetype entry is required exactly once")
        ordered = [found[0]] + [entry for entry in ordered if entry[0] != "mimetype"]
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name, data in ordered:
            info = zipfile.ZipInfo(name, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3  # Unix, independent of the host OS
            info.external_attr = 0o644 << 16
            info.internal_attr = 0
            info.flag_bits = 0
            archive.writestr(info, data)
    return buffer.getvalue()
