"""Image records, license policy, legal local download, hashing and thumbnails.

The download guard is the single choke point: bytes are written to data/images only
when permission_status == 'local_copy_allowed'. Unknown or restricted images stay
link-only (source page link + optional remote display URL).
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from ..config import LicensePolicy
from .common import dumps, image_code, loads, now_iso, place_code, row_to_dict
from .context import AppContext

log = logging.getLogger(__name__)

ALLOWED_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/tiff": ".tif"}


class DownloadNotAllowed(Exception):
    pass


@dataclass
class ImageCandidate:
    provider: str
    external_id: str
    title: str | None
    source_page_url: str
    original_url: str | None
    display_url: str | None
    description: str | None = None
    creator: str | None = None
    attribution_text: str | None = None
    attribution_url: str | None = None
    license_id: str | None = None  # normalized, e.g. cc-by-sa-4.0
    license_short: str | None = None  # as shown by provider, e.g. "CC BY-SA 4.0"
    license_url: str | None = None
    width: int | None = None
    height: int | None = None
    mime_type: str | None = None
    bytes: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    categories: list[str] = field(default_factory=list)
    date_taken: str | None = None
    restrictions: str | None = None
    view_type: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)


def normalize_license(short_name: str | None, license_url: str | None = None) -> str | None:
    if not short_name and not license_url:
        return None
    text = (short_name or "").strip().lower()
    url = (license_url or "").lower()
    if "cc0" in text or "/zero/" in url:
        return "cc0"
    if "public domain" in text or text in ("pd", "pd-self", "pd-old", "pd-author", "pd-us") or "publicdomain/mark" in url:
        return "public domain"
    m = re.match(r"cc[\s-]*(by(?:-nc-sa|-nc-nd|-sa|-nc|-nd)?)[\s-]*([0-9.]+)?", text.replace(" ", "-"))
    if m:
        variant = m.group(1)
        version = m.group(2) or ""
        return f"cc-{variant}" + (f"-{version}" if version else "")
    m = re.search(r"creativecommons\.org/licenses/(by[a-z-]*)/([0-9.]+)", url)
    if m:
        return f"cc-{m.group(1)}-{m.group(2)}"
    if "gfdl" in text:
        return "gfdl"
    if "fal" in text or "art libre" in text:
        return "fal"
    if "attribution" == text:
        return "attribution"
    return text or None


def evaluate_permission(license_id: str | None, policy: LicensePolicy, restrictions: str | None = None) -> tuple[str, str]:
    """Return (permission_status, reason)."""
    if not license_id:
        return "unknown", "no license metadata"
    lid = license_id.lower()
    for marker in policy.blocked_markers:
        if marker in lid:
            return "link_only", f"license contains '{marker}' (not permitted for local copy)"
    for allowed in policy.local_copy_allowed:
        if lid == allowed or lid.startswith(allowed + "-") or lid.startswith(allowed + " "):
            reason = f"license '{license_id}' permits local copy with attribution"
            if restrictions:
                reason += f"; note restrictions: {restrictions}"
            return "local_copy_allowed", reason
    if lid.startswith("cc-by") and not any(m in lid for m in ("-nc", "-nd")):
        return "local_copy_allowed", f"license '{license_id}' permits local copy with attribution"
    return "link_only", f"license '{license_id}' not in local-copy allow list"


def dhash(image: Image.Image, size: int = 8) -> str:
    gray = ImageOps.exif_transpose(image).convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    bits = []
    for row in range(size):
        for col in range(size):
            left = pixels[row * (size + 1) + col]
            right = pixels[row * (size + 1) + col + 1]
            bits.append("1" if left > right else "0")
    return f"{int(''.join(bits), 2):0{size * size // 4}x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


class ImageService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.policy = ctx.config.license_policy

    # ----------------------------------------------------------------- records
    def upsert_image(self, cand: ImageCandidate) -> int:
        license_id = cand.license_id or normalize_license(cand.license_short, cand.license_url)
        status, reason = evaluate_permission(license_id, self.policy, cand.restrictions)
        with self.ctx.db.transaction() as conn:
            row = conn.execute("SELECT id, permission_status, local_path FROM images WHERE provider=? AND external_id=?", (cand.provider, cand.external_id)).fetchone()
            attribution = cand.attribution_text or _default_attribution(cand.creator, cand.license_short or license_id, cand.provider)
            if row:
                conn.execute(
                    """UPDATE images SET source_page_url=?, original_url=?, display_url=?, title=?, description=?, creator=?,
                       attribution_text=?, attribution_url=?, license_id=?, license_url=?, license_short=?, permission_status=?,
                       permission_reason=?, license_verified_at=?, width=?, height=?, mime_type=?, bytes=COALESCE(bytes, ?),
                       latitude=?, longitude=?, categories_json=?, date_taken=?, last_checked_at=? WHERE id=?""",
                    (cand.source_page_url, cand.original_url, cand.display_url, cand.title, cand.description, cand.creator,
                     attribution, cand.attribution_url or cand.source_page_url, license_id, cand.license_url, cand.license_short,
                     status, reason, now_iso(), cand.width, cand.height, cand.mime_type, cand.bytes, cand.latitude, cand.longitude,
                     dumps(cand.categories), cand.date_taken, now_iso(), row["id"]),
                )
                image_id = int(row["id"])
                if row["local_path"] and status != "local_copy_allowed":
                    # License changed to something restrictive: drop the local copy, keep the record.
                    self._remove_local_files(conn, image_id, reason="license no longer permits local copy")
                return image_id
            cur = conn.execute(
                """INSERT INTO images (provider, external_id, source_page_url, original_url, display_url, title, description, creator,
                   attribution_text, attribution_url, license_id, license_url, license_short, permission_status, permission_reason,
                   license_verified_at, width, height, mime_type, bytes, latitude, longitude, categories_json, date_taken, view_type, retrieved_at, last_checked_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cand.provider, cand.external_id, cand.source_page_url, cand.original_url, cand.display_url, cand.title, cand.description,
                 cand.creator, attribution, cand.attribution_url or cand.source_page_url, license_id, cand.license_url, cand.license_short,
                 status, reason, now_iso(), cand.width, cand.height, cand.mime_type, cand.bytes, cand.latitude, cand.longitude,
                 dumps(cand.categories), cand.date_taken, cand.view_type, now_iso(), now_iso()),
            )
            return int(cur.lastrowid)

    def associate(self, place_id: int, image_id: int, score: float, reasons: list[str], confidence: float | None = None) -> None:
        with self.ctx.db.transaction() as conn:
            conn.execute(
                """INSERT INTO place_images (place_id, image_id, match_score, match_reasons_json, confidence_score)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(place_id, image_id) DO UPDATE SET
                     match_score=CASE WHEN place_images.verified_by_user=1 THEN place_images.match_score ELSE excluded.match_score END,
                     match_reasons_json=CASE WHEN place_images.verified_by_user=1 THEN place_images.match_reasons_json ELSE excluded.match_reasons_json END,
                     confidence_score=excluded.confidence_score""",
                (place_id, image_id, score, dumps(reasons), confidence if confidence is not None else min(1.0, score / 8.0)),
            )
            self._ensure_primary(conn, place_id)
            from .ingest import Ingestor

            Ingestor.refresh_counters(conn, place_id)

    @staticmethod
    def _ensure_primary(conn: sqlite3.Connection, place_id: int) -> None:
        has_primary = conn.execute(
            "SELECT 1 FROM place_images WHERE place_id=? AND is_primary=1 AND association_status!='rejected'", (place_id,)
        ).fetchone()
        if has_primary:
            return
        best = conn.execute(
            """SELECT pi.image_id FROM place_images pi JOIN images i ON i.id=pi.image_id
               WHERE pi.place_id=? AND pi.association_status!='rejected'
               ORDER BY pi.verified_by_user DESC, (i.local_path IS NOT NULL) DESC, pi.match_score DESC LIMIT 1""",
            (place_id,),
        ).fetchone()
        if best:
            conn.execute("UPDATE place_images SET is_primary=0 WHERE place_id=?", (place_id,))
            conn.execute("UPDATE place_images SET is_primary=1 WHERE place_id=? AND image_id=?", (place_id, best["image_id"]))

    def set_association(self, place_id: int, image_id: int, status: str, notes: str | None = None, make_primary: bool | None = None) -> None:
        if status not in ("suggested", "user_verified", "rejected"):
            raise ValueError("invalid association status")
        with self.ctx.db.transaction() as conn:
            conn.execute(
                "UPDATE place_images SET association_status=?, association_type=?, verified_by_user=?, notes=COALESCE(?, notes) WHERE place_id=? AND image_id=?",
                (status, status, 1 if status == "user_verified" else 0, notes, place_id, image_id),
            )
            if status == "rejected":
                conn.execute("UPDATE place_images SET is_primary=0 WHERE place_id=? AND image_id=?", (place_id, image_id))
            if make_primary:
                conn.execute("UPDATE place_images SET is_primary=0 WHERE place_id=?", (place_id,))
                conn.execute("UPDATE place_images SET is_primary=1 WHERE place_id=? AND image_id=?", (place_id, image_id))
            self._ensure_primary(conn, place_id)
            from .ingest import Ingestor

            Ingestor.refresh_counters(conn, place_id)

    def report_issue(self, image_id: int, issue: str) -> None:
        with self.ctx.db.transaction() as conn:
            conn.execute("UPDATE images SET reported_issue=? WHERE id=?", (issue[:500], image_id))

    def get_image(self, image_id: int) -> dict[str, Any] | None:
        conn = self.ctx.db.conn()
        row = conn.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        d = row_to_dict(row)
        if d:
            d["categories"] = loads(d.pop("categories_json", "[]"), [])
            d["places"] = [dict(r) for r in conn.execute(
                "SELECT pi.place_id, p.canonical_name, pi.match_score, pi.association_status FROM place_images pi JOIN places p ON p.id=pi.place_id WHERE pi.image_id=?",
                (image_id,)).fetchall()]
        return d

    # ---------------------------------------------------------------- download
    def download(self, image_id: int, place_id: int | None = None) -> dict[str, Any]:
        """Download a permitted image to data/images/<place>/<img>.<ext>; atomic; hashed; thumbnail."""
        conn = self.ctx.db.conn()
        row = conn.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        if not row:
            raise KeyError(image_id)
        if row["permission_status"] != "local_copy_allowed":
            with self.ctx.db.transaction() as wconn:
                wconn.execute("UPDATE images SET download_status='not_allowed', download_error=? WHERE id=?",
                              (f"permission_status={row['permission_status']}", image_id))
            raise DownloadNotAllowed(f"image {image_id} permission_status={row['permission_status']}")
        if row["local_path"] and (self.ctx.config.images_dir / row["local_path"]).is_file():
            return {"image_id": image_id, "local_path": row["local_path"], "status": "already_downloaded"}
        url = row["display_url"] or row["original_url"]
        if not url:
            raise ValueError("no download URL")
        if place_id is None:
            pr = conn.execute("SELECT place_id FROM place_images WHERE image_id=? ORDER BY is_primary DESC LIMIT 1", (image_id,)).fetchone()
            place_id = pr["place_id"] if pr else 0
        folder = place_code(place_id) if place_id else "unassigned"
        data, mime = self._fetch_bytes(url)
        ext = ALLOWED_MIME.get(mime)
        if ext is None:
            raise ValueError(f"unsupported content type {mime}")
        sha = hashlib.sha256(data).hexdigest()
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            width, height = img.size
            phash = dhash(img)
            thumb = ImageOps.exif_transpose(img).convert("RGB")
            thumb.thumbnail((self.policy.thumbnail_width, self.policy.thumbnail_width))
            thumb_buf = io.BytesIO()
            thumb.save(thumb_buf, format="JPEG", quality=82, optimize=True)
        rel_path = f"{folder}/{image_code(image_id)}{ext}"
        rel_thumb = f"{folder}/{image_code(image_id)}.jpg"
        _atomic_write(self.ctx.config.images_dir / rel_path, data)
        _atomic_write(self.ctx.config.thumbnails_dir / rel_thumb, thumb_buf.getvalue())
        with self.ctx.db.transaction() as wconn:
            wconn.execute(
                """UPDATE images SET local_path=?, thumbnail_path=?, sha256=?, perceptual_hash=?, width=?, height=?, mime_type=?, bytes=?,
                   download_status='downloaded', download_error=NULL, last_checked_at=? WHERE id=?""",
                (rel_path, rel_thumb, sha, phash, width, height, mime, len(data), now_iso(), image_id),
            )
            for pr in wconn.execute("SELECT place_id FROM place_images WHERE image_id=?", (image_id,)).fetchall():
                from .ingest import Ingestor

                Ingestor.refresh_counters(wconn, pr["place_id"])
        return {"image_id": image_id, "local_path": rel_path, "sha256": sha, "perceptual_hash": phash, "status": "downloaded"}

    def _fetch_bytes(self, url: str) -> tuple[bytes, str]:
        from urllib.parse import urlsplit

        host = urlsplit(url).hostname or ""
        if not host.endswith(("wikimedia.org", "wikipedia.org")) and not self.ctx.config.raw.get("allow_any_image_host"):
            raise DownloadNotAllowed(f"download host {host} not allow-listed")
        limit = self.policy.max_download_bytes
        resp = self.ctx.http.get(url, stream=True, timeout=120)
        try:
            resp.raise_for_status()
            mime = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if mime not in ALLOWED_MIME:
                raise ValueError(f"unsupported content type {mime}")
            declared = resp.headers.get("content-length")
            if declared and int(declared) > limit:
                raise ValueError("image exceeds size limit")
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes(65536):
                total += len(chunk)
                if total > limit:
                    raise ValueError("image exceeds size limit")
                chunks.append(chunk)
            return b"".join(chunks), mime
        finally:
            resp.close()

    def download_for_place(self, place_id: int, limit: int | None = None) -> dict[str, Any]:
        limit = limit or self.policy.max_images_per_place
        conn = self.ctx.db.conn()
        rows = conn.execute(
            """SELECT i.id FROM place_images pi JOIN images i ON i.id=pi.image_id
               WHERE pi.place_id=? AND pi.association_status!='rejected' AND i.permission_status='local_copy_allowed'
                 AND i.local_path IS NULL AND i.download_status IN ('not_downloaded','failed') AND pi.match_score >= ?
               ORDER BY pi.verified_by_user DESC, pi.match_score DESC LIMIT ?""",
            (place_id, self.policy.min_match_score, limit),
        ).fetchall()
        done, failed = 0, 0
        for r in rows:
            try:
                self.download(r["id"], place_id)
                done += 1
            except Exception as exc:  # keep going; record error
                failed += 1
                with self.ctx.db.transaction() as wconn:
                    wconn.execute("UPDATE images SET download_status='failed', download_error=? WHERE id=?", (str(exc)[:300], r["id"]))
                log.warning("download failed for image %s: %s", r["id"], exc)
        return {"place_id": place_id, "downloaded": done, "failed": failed, "considered": len(rows)}

    def remove_local_copy(self, image_id: int, reason: str = "user request") -> None:
        with self.ctx.db.transaction() as conn:
            self._remove_local_files(conn, image_id, reason)

    def _remove_local_files(self, conn: sqlite3.Connection, image_id: int, reason: str) -> None:
        row = conn.execute("SELECT local_path, thumbnail_path FROM images WHERE id=?", (image_id,)).fetchone()
        if not row:
            return
        for base, rel in ((self.ctx.config.images_dir, row["local_path"]), (self.ctx.config.thumbnails_dir, row["thumbnail_path"])):
            if rel:
                path = _safe_join(base, rel)
                if path and path.is_file():
                    path.unlink()
        conn.execute(
            "UPDATE images SET local_path=NULL, thumbnail_path=NULL, download_status='removed', download_error=? WHERE id=?",
            (reason[:300], image_id),
        )
        for pr in conn.execute("SELECT place_id FROM place_images WHERE image_id=?", (image_id,)).fetchall():
            from .ingest import Ingestor

            Ingestor.refresh_counters(conn, pr["place_id"])

    # --------------------------------------------------------------- duplicates
    def find_duplicates(self, max_distance: int = 6) -> list[dict[str, Any]]:
        conn = self.ctx.db.conn()
        rows = conn.execute("SELECT id, sha256, perceptual_hash, local_path FROM images WHERE local_path IS NOT NULL").fetchall()
        groups: list[dict[str, Any]] = []
        by_sha: dict[str, list[int]] = {}
        for r in rows:
            by_sha.setdefault(r["sha256"], []).append(r["id"])
        for sha, ids in by_sha.items():
            if len(ids) > 1:
                groups.append({"type": "exact", "sha256": sha, "image_ids": ids})
        hashed = [(r["id"], r["perceptual_hash"]) for r in rows if r["perceptual_hash"]]
        for i in range(len(hashed)):
            for j in range(i + 1, len(hashed)):
                if hashed[i][1] == hashed[j][1]:
                    continue
                if hamming(hashed[i][1], hashed[j][1]) <= max_distance:
                    groups.append({"type": "near", "image_ids": [hashed[i][0], hashed[j][0]], "distance": hamming(hashed[i][1], hashed[j][1])})
        return groups

    def unassigned_geotagged(self, limit: int = 200) -> list[dict[str, Any]]:
        conn = self.ctx.db.conn()
        rows = conn.execute(
            """SELECT i.* FROM images i WHERE i.latitude IS NOT NULL AND NOT EXISTS (SELECT 1 FROM place_images pi WHERE pi.image_id=i.id)
               ORDER BY i.retrieved_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [row_to_dict(r) for r in rows]  # type: ignore[misc]


def _default_attribution(creator: str | None, license_short: str | None, provider: str) -> str:
    who = creator or "Unknown author"
    where = "Wikimedia Commons" if provider == "commons" else provider
    lic = license_short or "license unknown"
    return f"{who}, {where}, {lic}"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _safe_join(base: Path, rel: str) -> Path | None:
    """Resolve rel inside base; reject traversal."""
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return None
    return candidate
