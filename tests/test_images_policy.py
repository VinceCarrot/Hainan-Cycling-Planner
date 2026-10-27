import hashlib
import io

import pytest
from PIL import Image

from hainan_explorer.config import LicensePolicy
from hainan_explorer.services.images import (
    DownloadNotAllowed,
    ImageCandidate,
    ImageService,
    dhash,
    evaluate_permission,
    hamming,
    normalize_license,
)
from hainan_explorer.services.ingest import Candidate, Ingestor


@pytest.mark.parametrize("short,url,expected", [
    ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0", "cc-by-sa-4.0"),
    ("CC0", "https://creativecommons.org/publicdomain/zero/1.0/", "cc0"),
    ("Public domain", None, "public domain"),
    ("CC BY-NC-ND 2.0", None, "cc-by-nc-nd-2.0"),
    (None, "https://creativecommons.org/licenses/by/3.0", "cc-by-3.0"),
    (None, None, None),
])
def test_normalize_license(short, url, expected):
    assert normalize_license(short, url) == expected


def test_permission_policy_blocks_unknown_nc_nd_and_allows_open():
    policy = LicensePolicy()
    assert evaluate_permission(None, policy)[0] == "unknown"
    assert evaluate_permission("cc-by-nc-sa-4.0", policy)[0] == "link_only"
    assert evaluate_permission("cc-by-nd-4.0", policy)[0] == "link_only"
    assert evaluate_permission("cc-by-sa-4.0", policy)[0] == "local_copy_allowed"
    assert evaluate_permission("cc0", policy)[0] == "local_copy_allowed"
    assert evaluate_permission("public domain", policy)[0] == "local_copy_allowed"
    assert evaluate_permission("copyrighted", policy)[0] == "link_only"


def _img(ext_id="File:A.jpg", lic="CC BY-SA 4.0", **kw):
    return ImageCandidate(provider="commons", external_id=ext_id, title=ext_id, source_page_url=f"https://commons.wikimedia.org/wiki/{ext_id}",
                          original_url=f"https://upload.wikimedia.org/x/{ext_id}", display_url=f"https://upload.wikimedia.org/x/thumb/{ext_id}",
                          license_short=lic, license_url=None, creator="Tester", **kw)


def test_unknown_license_image_is_never_downloaded(ctx):
    svc = ImageService(ctx)
    image_id = svc.upsert_image(_img("File:Unknown.jpg", lic=None))
    assert svc.get_image(image_id)["permission_status"] == "unknown"
    with pytest.raises(DownloadNotAllowed):
        svc.download(image_id)
    assert svc.get_image(image_id)["download_status"] == "not_allowed"
    assert not list(ctx.config.images_dir.rglob("*"))


def test_nc_license_is_link_only_and_download_refused(ctx):
    svc = ImageService(ctx)
    image_id = svc.upsert_image(_img("File:NC.jpg", lic="CC BY-NC 4.0"))
    assert svc.get_image(image_id)["permission_status"] == "link_only"
    with pytest.raises(DownloadNotAllowed):
        svc.download(image_id)


def _fake_response(data: bytes, mime="image/jpeg"):
    class R:
        status_code = 200
        headers = {"content-type": mime, "content-length": str(len(data))}

        def raise_for_status(self):
            pass

        def iter_bytes(self, n):
            for i in range(0, len(data), n):
                yield data[i:i + n]

        def close(self):
            pass

    return R()


def _jpeg_bytes(color=(200, 50, 50), size=(640, 480)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def test_allowed_image_downloads_atomically_with_hashes_and_thumbnail(ctx, monkeypatch):
    place = Ingestor(ctx).ingest(Candidate(provider="osm", external_id="node/1", name="测试灯塔", latitude=19.0, longitude=110.0, category="lighthouse"))
    svc = ImageService(ctx)
    data = _jpeg_bytes()
    monkeypatch.setattr(ctx.http, "get", lambda url, **kw: _fake_response(data))
    image_id = svc.upsert_image(_img("File:Allowed.jpg", lic="CC BY 4.0"))
    svc.associate(place.place_id, image_id, 6.0, ["name_in_title"])
    result = svc.download(image_id, place.place_id)
    assert result["status"] == "downloaded"
    local = ctx.config.images_dir / result["local_path"]
    assert local.is_file() and local.parent.name == f"HN{place.place_id:06d}"
    assert not list(ctx.config.images_dir.rglob("*.part"))
    img = svc.get_image(image_id)
    assert img["sha256"] == hashlib.sha256(data).hexdigest()
    assert img["perceptual_hash"] and img["thumbnail_path"]
    assert (ctx.config.thumbnails_dir / img["thumbnail_path"]).is_file()
    assert svc.download(image_id, place.place_id)["status"] == "already_downloaded"
    svc.remove_local_copy(image_id)
    img2 = svc.get_image(image_id)
    assert img2["local_path"] is None and img2["download_status"] == "removed" and not local.exists()


def test_download_rejects_non_wikimedia_hosts_and_oversize(ctx, monkeypatch):
    svc = ImageService(ctx)
    image_id = svc.upsert_image(ImageCandidate(provider="web", external_id="x", title="x", source_page_url="https://example.com/p",
                                               original_url="https://example.com/a.jpg", display_url=None, license_short="CC BY 4.0"))
    with pytest.raises(DownloadNotAllowed):
        svc.download(image_id)
    ctx.config.raw["allow_any_image_host"] = True
    big = b"x" * (ctx.config.license_policy.max_download_bytes + 1)
    monkeypatch.setattr(ctx.http, "get", lambda url, **kw: _fake_response(big))
    with pytest.raises(ValueError):
        svc.download(image_id)


def test_dhash_detects_near_duplicates():
    a = Image.new("RGB", (100, 100), (10, 10, 10))
    for x in range(50):
        for y in range(100):
            a.putpixel((x, y), (240, 240, 240))
    b = a.resize((60, 60))
    c = Image.new("RGB", (100, 100), (0, 0, 0))
    for x in range(100):
        for y in range(50):
            c.putpixel((x, y), (255, 255, 255))
    assert hamming(dhash(a), dhash(b)) <= 4
    assert hamming(dhash(a), dhash(c)) > 10


def test_license_change_removes_local_copy_but_keeps_record(ctx, monkeypatch):
    svc = ImageService(ctx)
    data = _jpeg_bytes((10, 100, 200))
    monkeypatch.setattr(ctx.http, "get", lambda url, **kw: _fake_response(data))
    image_id = svc.upsert_image(_img("File:Changing.jpg", lic="CC BY-SA 4.0"))
    svc.download(image_id, 0)
    assert svc.get_image(image_id)["local_path"]
    svc.upsert_image(_img("File:Changing.jpg", lic="CC BY-NC 4.0"))
    img = svc.get_image(image_id)
    assert img["local_path"] is None and img["permission_status"] == "link_only"
