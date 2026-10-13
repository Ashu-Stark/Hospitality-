"""Photo proof: the server stamps time, job and worker onto the image, stores it and records a SHA-256.

The stamped JPEG (at most 1280 px, far below MongoDB's 16 MB document limit) is stored in `photo_blobs` as BSON
binary, so deployments need no persistent disk; the metadata lives in `photos`. Every read re-hashes the bytes.

The timestamp is the server's clock at upload, never the phone's EXIF. Limit: this cannot stop someone
photographing a screen or a printout.
"""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime

from bson import Binary
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from .. import mongo
from .errors import Conflict, Invalid, NotFound

MAX_SIDE = 1280
MAX_BYTES = 12 * 1024 * 1024


def _font(size: int):
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def save(tid: str, job_id: str, kind: str, data: bytes, taken_by: str) -> dict:
    if kind not in ("before", "after"):
        raise Invalid("kind must be before or after")
    if len(data) > MAX_BYTES:
        raise Invalid("Photo is larger than 12 MB.")
    j = mongo.col("jobs").find_one({"id": job_id, "tenant_id": tid}, {"assigned_to": 1, "status": 1})
    if not j:
        raise NotFound("Job not found")
    if j["assigned_to"] != taken_by:
        raise Conflict("Only the assigned worker can add photos to this job.")
    if kind == "before" and j["status"] != "accepted":
        raise Conflict("The before photo is taken right after accepting.")
    if kind == "after" and j["status"] != "in_progress":
        raise Conflict("The after photo is taken when the job is in progress.")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise Invalid("That file is not an image.") from None
    ts = datetime.now().astimezone().replace(microsecond=0)
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    w, h = img.size
    bar = max(34, h // 14)
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([0, h - bar, w, h], fill=(11, 11, 11, 190))
    draw.rectangle([0, h - bar, max(8, bar // 5), h], fill=((12, 163, 12) if kind == "after" else (250, 178, 25)) + (255,))
    text = f"HOI · {kind.upper()} · {ts.strftime('%d %b %Y %H:%M:%S %Z').strip()} · job {job_id[-8:]} · {taken_by}"
    draw.text((bar // 2 + 8, h - bar + bar // 4), text, fill=(255, 255, 255, 255), font=_font(max(12, bar // 2 - 2)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    raw = buf.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    pid = mongo.new_id("ph")
    blobs = mongo.col("photo_blobs")
    blobs.insert_one({"id": pid, "tenant_id": tid, "job_id": job_id, "data": Binary(raw)})
    doc = {
        "id": pid,
        "tenant_id": tid,
        "job_id": job_id,
        "kind": kind,
        "sha256": digest,
        "server_ts": ts.astimezone(UTC),
        "taken_by": taken_by,
        "width": w,
        "height": h,
    }
    try:
        mongo.col("photos").insert_one(doc)
    except Exception:
        blobs.delete_one({"id": pid, "tenant_id": tid})  # compensating write: no orphan blob
        raise
    return meta(tid, pid)


def meta(tid: str, pid: str) -> dict:
    r = mongo.col("photos").find_one({"id": pid, "tenant_id": tid})
    if not r:
        raise NotFound("Photo not found")
    p = mongo.clean(r, aware=("server_ts",))
    p["verified"] = verify(tid, r)
    return p


def for_job(tid: str, job_id: str) -> dict[str, dict]:
    rows = (
        mongo.col("photos")
        .find({"job_id": job_id, "tenant_id": tid}, {"id": 1, "kind": 1, "server_ts": 1})
        .sort([("server_ts", 1), ("_id", 1)])
    )
    return {r["kind"]: meta(tid, r["id"]) for r in rows}


def _blob(tid: str, pid: str) -> bytes | None:
    b = mongo.col("photo_blobs").find_one({"id": pid, "tenant_id": tid}, {"data": 1})
    return bytes(b["data"]) if b else None


def file_bytes(tid: str, pid: str) -> bytes:
    if not mongo.col("photos").find_one({"id": pid, "tenant_id": tid}, {"id": 1}):
        raise NotFound("Photo not found")
    data = _blob(tid, pid)
    if data is None:
        raise NotFound("Photo not found")
    return data


def verify(tid: str, row: dict) -> bool:
    data = _blob(tid, row.get("id", ""))
    return data is not None and hashlib.sha256(data).hexdigest() == row.get("sha256")
