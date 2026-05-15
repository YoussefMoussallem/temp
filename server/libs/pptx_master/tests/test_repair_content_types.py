"""Repair pass for malformed ``[Content_Types].xml``.

Real-world templates routinely ship Content-Types manifests that omit
Default entries for image extensions actually present in the package.
PowerPoint accepts these silently; python-pptx refuses to parse them
(``no content-type for partname '/ppt/media/image-N.png'``).

Tests synthesise a tiny zip that resembles a .pptx fragment so we can
exercise the repair pass without depending on any specific real
template being present.
"""

from __future__ import annotations

import io
import zipfile

from lxml import etree

from pptx_master.master_extractor import _repair_content_types


_OPC_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def _build_zip(content_types_xml: bytes, members: dict[str, bytes]) -> bytes:
    """Wrap ``[Content_Types].xml`` + the given members into a zip."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types_xml)
        for name, body in members.items():
            z.writestr(name, body)
    return out.getvalue()


def _parse_defaults(zipped: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(zipped), "r") as z:
        ct_xml = z.read("[Content_Types].xml")
    root = etree.fromstring(ct_xml)
    out = {}
    for child in root:
        tag = etree.QName(child).localname
        if tag == "Default":
            ext = (child.get("Extension") or "").lower()
            if ext:
                out[ext] = child.get("ContentType") or ""
    return out


_BASE_CT = (
    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<Types xmlns="{_OPC_NS}">'
    f'  <Default Extension="xml" ContentType="application/xml"/>'
    f'  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    f"</Types>"
).encode()


def test_no_op_when_manifest_already_complete():
    members = {
        "ppt/media/img1.png": b"\x89PNG\r\n\x1a\n",
        "ppt/somefile.xml": b"<a/>",
    }
    ct_full = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{_OPC_NS}">'
        f'  <Default Extension="xml" ContentType="application/xml"/>'
        f'  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        f'  <Default Extension="png" ContentType="image/png"/>'
        f"</Types>"
    ).encode()
    zipped = _build_zip(ct_full, members)
    out = _repair_content_types(zipped)
    # Already complete → returns the original bytes object.
    assert out is zipped


def test_adds_missing_png_default():
    members = {
        "ppt/media/image-1-1.png": b"\x89PNG\r\n\x1a\n",
        "ppt/somefile.xml": b"<a/>",
    }
    zipped = _build_zip(_BASE_CT, members)
    repaired = _repair_content_types(zipped)
    assert repaired is not zipped, "should have rewritten the package"
    defaults = _parse_defaults(repaired)
    assert defaults.get("png") == "image/png"
    # Existing entries preserved.
    assert defaults.get("xml") == "application/xml"


def test_adds_multiple_missing_image_defaults():
    members = {
        "ppt/media/a.png": b"\x89PNG\r\n\x1a\n",
        "ppt/media/b.jpeg": b"\xff\xd8",
        "ppt/media/c.gif": b"GIF89a",
    }
    zipped = _build_zip(_BASE_CT, members)
    repaired = _repair_content_types(zipped)
    defaults = _parse_defaults(repaired)
    assert defaults.get("png") == "image/png"
    assert defaults.get("jpeg") == "image/jpeg"
    assert defaults.get("gif") == "image/gif"


def test_skips_extension_already_covered_by_override():
    """When a part has a per-part Override, we don't need to add a
    Default for its extension. The repair pass should respect that and
    leave the manifest alone."""
    members = {
        "ppt/media/special.png": b"\x89PNG\r\n\x1a\n",
    }
    ct_with_override = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{_OPC_NS}">'
        f'  <Default Extension="xml" ContentType="application/xml"/>'
        f'  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        f'  <Override PartName="/ppt/media/special.png" ContentType="image/png"/>'
        f"</Types>"
    ).encode()
    zipped = _build_zip(ct_with_override, members)
    repaired = _repair_content_types(zipped)
    # Either no-op (perfect), or rewrote without adding png Default
    # (also acceptable). What we must NOT do is double-declare it.
    defaults = _parse_defaults(repaired)
    assert defaults.get("png") is None


def test_returns_original_bytes_for_non_zip():
    not_a_zip = b"this is definitely not a zip file"
    assert _repair_content_types(not_a_zip) is not_a_zip


def test_returns_original_bytes_when_content_types_missing():
    # A zip without [Content_Types].xml is malformed for OPC but the
    # repair pass shouldn't try to invent one — let pptx raise its own
    # clear error.
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("not-content-types.xml", b"<a/>")
    not_opc = out.getvalue()
    assert _repair_content_types(not_opc) is not_opc


def test_ignores_unknown_extensions():
    """An extension we don't have a content-type mapping for (say,
    .xyz) shouldn't be auto-added — we only repair known media types."""
    members = {"ppt/media/file.xyz": b"\x00"}
    zipped = _build_zip(_BASE_CT, members)
    repaired = _repair_content_types(zipped)
    defaults = _parse_defaults(repaired)
    assert "xyz" not in defaults
