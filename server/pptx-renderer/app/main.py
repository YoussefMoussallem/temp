"""pptx-renderer sidecar — turn .pptx slides into PNGs via LibreOffice.

This is a tiny FastAPI service that wraps ``libreoffice --headless
--convert-to png``. Backend's ``app/services/pptx_renderer.py`` POSTs
multipart-encoded .pptx bytes here; we render every slide, zip the
PNGs, and return the zip. Caller filters by index.

Why a sidecar (not in-process):
* LibreOffice isn't safe to fork in a Python web server: it leaves
  file handles + temp directories that pile up across requests.
* Cold start is 3-4s; running it as a subprocess from inside the
  backend service would block the asyncio event loop on every
  startup. A separate service amortises that cost across many
  requests.
* The Docker image is ~300 MB. Keeping it out of the backend image
  reduces deploy time when only the agent code changes.

Endpoint:

  POST /render
    multipart/form-data:
      file: the .pptx bytes
      slides (optional): comma-separated 1-based indices to include
                         in the response zip (defaults to all)
    -> 200, application/zip with slide-1.png ... slide-N.png

Failure modes returned as 4xx/5xx with JSON detail:
  400 — file missing, file empty, file not a .pptx
  422 — LibreOffice can't open the file
  504 — render exceeded ``RENDER_TIMEOUT_SECONDS`` (default 90s)
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response


_RENDER_TIMEOUT_SECONDS = float(os.environ.get("RENDER_TIMEOUT_SECONDS", "90"))
_LIBREOFFICE_BIN = os.environ.get("LIBREOFFICE_BIN", "libreoffice")
_PDFTOPPM_BIN = os.environ.get("PDFTOPPM_BIN", "pdftoppm")
_RENDER_DPI = int(os.environ.get("RENDER_DPI", "96"))
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_SLIDE_FILENAME_RE = re.compile(r".*?-?(\d+)\.png$", re.IGNORECASE)


app = FastAPI(title="pptx-renderer", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "pptx-renderer"}


@app.post("/render")
async def render(
    file: UploadFile = File(...),
    slides: str | None = Form(default=None),
) -> Response:
    """Render the slides in ``file`` to PNGs and return them zipped."""
    if file.filename and not file.filename.lower().endswith((".pptx", ".potx")):
        raise HTTPException(status_code=400, detail="Expected .pptx or .potx")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")

    requested_indices = _parse_indices(slides)

    with tempfile.TemporaryDirectory(prefix="pptx-render-") as tmpdir:
        tmp = Path(tmpdir)
        in_path = tmp / "input.pptx"
        in_path.write_bytes(data)
        out_dir = tmp / "out"
        out_dir.mkdir()

        try:
            # Two-stage: .pptx → .pdf (libreoffice gives us the
            # whole deck in one PDF), then .pdf → .png (pdftoppm
            # writes one PNG per page). The intermediate PDF lives in
            # ``tmp`` and is discarded with the temp dir.
            pdf_path = await _run_libreoffice_convert(in_path, tmp)
            await _run_pdftoppm(pdf_path, out_dir)
        except subprocess.CalledProcessError as e:
            raise HTTPException(
                status_code=422,
                detail=f"Render pipeline failed: {e.stderr or e}",
            ) from e
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail=f"Render exceeded {_RENDER_TIMEOUT_SECONDS:.0f}s timeout",
            )

        png_paths = _ordered_pngs(out_dir)
        if not png_paths:
            raise HTTPException(
                status_code=422,
                detail="LibreOffice produced no PNGs from the .pptx",
            )

        # Filter by requested indices (1-based). When unset, return all.
        if requested_indices:
            wanted = set(requested_indices)
            filtered = [p for idx, p in png_paths if idx in wanted]
        else:
            filtered = [p for _, p in png_paths]

        zip_bytes = _zip_pngs(filtered)
        return Response(content=zip_bytes, media_type="application/zip")


# ── Helpers ───────────────────────────────────────────────────────────


def _parse_indices(raw: str | None) -> list[int]:
    """Parse ``"1,3,5"`` → ``[1, 3, 5]``. Empty / None → ``[]``
    meaning 'no filter'. Non-numeric tokens are dropped silently."""
    if not raw:
        return []
    out: list[int] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return out


async def _run_libreoffice_convert(in_path: Path, work_dir: Path) -> Path:
    """Convert .pptx → .pdf via ``libreoffice --headless`` and return
    the PDF path.

    Why PDF instead of PNG directly: LibreOffice's ``--convert-to png``
    only renders the *first* slide of a multi-slide deck. Routing
    through PDF (libreoffice writes one PDF with all slides) and then
    splitting via pdftoppm gives us one PNG per slide reliably.

    Each invocation gets its own ``-env:UserInstallation`` profile
    dir so concurrent renders don't fight over a single user profile
    (LibreOffice locks it). Without this, a second request while one
    is in flight either hangs or aborts.
    """
    profile_dir = (work_dir / "lo-profile").as_uri()

    proc = await asyncio.create_subprocess_exec(
        _LIBREOFFICE_BIN,
        f"-env:UserInstallation={profile_dir}",
        "--headless",
        "--norestore",
        "--nolockcheck",
        "--nologo",
        "--convert-to",
        "pdf",
        "--outdir",
        str(work_dir),
        str(in_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=_RENDER_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode,
            cmd=_LIBREOFFICE_BIN,
            output=stdout,
            stderr=stderr.decode("utf-8", errors="replace"),
        )

    pdf_path = work_dir / (in_path.stem + ".pdf")
    if not pdf_path.exists():
        # LibreOffice silently swallows odd inputs; surface as a 422
        # via the calling handler.
        raise subprocess.CalledProcessError(
            1,
            cmd=_LIBREOFFICE_BIN,
            output=stdout,
            stderr="LibreOffice produced no PDF (input may be corrupt)",
        )
    return pdf_path


async def _run_pdftoppm(pdf_path: Path, out_dir: Path) -> None:
    """Split a PDF into one PNG per page via ``pdftoppm``.

    Files are written as ``page-1.png``, ``page-2.png``, ...
    The ``-png`` flag selects PNG over PNM; ``-r`` is the DPI; we
    default to 96 (CSS px parity) which gives us 1280×720-ish PNGs
    for a standard 16:9 deck — the right size for the curation grid
    without being so big the blob storage bill spikes.
    """
    proc = await asyncio.create_subprocess_exec(
        _PDFTOPPM_BIN,
        "-png",
        "-r",
        str(_RENDER_DPI),
        str(pdf_path),
        str(out_dir / "page"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=_RENDER_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode,
            cmd=_PDFTOPPM_BIN,
            output=stdout,
            stderr=stderr.decode("utf-8", errors="replace"),
        )


def _ordered_pngs(out_dir: Path) -> list[tuple[int, Path]]:
    """Return PNGs sorted by their slide index, paired with that index.

    LibreOffice emits ``input.png``, ``input1.png`` ... or
    ``input-1.png``, ``input-2.png`` depending on version. We extract
    the trailing digits and sort numerically, defaulting to position
    when no number is present (single-slide decks).
    """
    candidates: list[tuple[int, Path]] = []
    pngs = sorted(out_dir.glob("*.png"))
    for i, p in enumerate(pngs, start=1):
        m = _SLIDE_FILENAME_RE.match(p.name)
        idx = int(m.group(1)) if m else i
        candidates.append((idx, p))
    return sorted(candidates, key=lambda x: x[0])


def _zip_pngs(pngs: list[Path]) -> bytes:
    """Pack the rendered PNGs into a zip with stable
    ``slide-1.png``...``slide-N.png`` names so the client doesn't
    need to know about LibreOffice's local naming."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i, p in enumerate(pngs, start=1):
            zf.writestr(f"slide-{i}.png", p.read_bytes())
    return buf.getvalue()
