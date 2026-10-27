from hainan_cycling import create_app
from hainan_cycling.catalog.repository import REGION_ROUTE_ORDER


def test_home_page_renders():
    response = create_app().test_client().get("/")

    assert response.status_code == 200
    assert "海南骑行路书".encode() in response.data


def test_static_stylesheet_is_served():
    response = create_app().test_client().get("/static/css/app.css")

    assert response.status_code == 200
    assert b".sidebar-nav" in response.data


def test_attractions_endpoint_returns_only_approved(monkeypatch):
    from hainan_cycling.web import routes

    requested_statuses = []

    def fake_list_attractions(status=None):
        requested_statuses.append(status)
        return []

    monkeypatch.setattr(routes, "list_attractions", fake_list_attractions)
    response = create_app().test_client().get("/api/attractions")

    assert response.status_code == 200
    assert response.json == []
    assert requested_statuses == ["approved"]


def test_attractions_endpoint_passes_status_filter(monkeypatch):
    from hainan_cycling.web import routes

    requested_statuses = []
    monkeypatch.setattr(
        routes,
        "list_attractions",
        lambda status=None: requested_statuses.append(status) or [],
    )
    response = create_app().test_client().get("/api/attractions?status=approved")

    assert response.status_code == 200
    assert response.json == []
    assert requested_statuses == ["approved"]


def test_candidate_endpoint_returns_researched_batch():
    from hainan_cycling.catalog.repository import list_attractions

    response = create_app().test_client().get("/api/attractions?status=candidate")

    assert response.status_code == 200
    assert len(response.json) == len(list_attractions(status="candidate"))
    assert len(response.json) > 0
    assert all(item["status"] == "candidate" for item in response.json)
    region_order = {region: index for index, region in enumerate(REGION_ROUTE_ORDER)}
    region_indexes = [region_order[item["region"]] for item in response.json]
    assert region_indexes == sorted(region_indexes)


SIDEBAR_PAGES = (
    "map",
    "library",
    "review",
    "itinerary",
    "lodging",
    "export",
    "settings",
)


def test_home_page_lists_sidebar_pages_and_views():
    html = create_app().test_client().get("/").data.decode()

    for page in SIDEBAR_PAGES:
        assert f'href="#/{page}"' in html
        assert f'data-view="{page}"' in html
    for label in ("环岛地图", "景点库", "待审核景点", "行程规划", "住宿与补给", "Garmin 导出", "设置与假设"):
        assert label in html


def test_static_script_switches_pages_by_hash():
    response = create_app().test_client().get("/static/js/app.js")

    assert response.status_code == 200
    assert b"hashchange" in response.data
    assert b'"/api/attractions?status=candidate"' in response.data


def test_favicon_is_linked_and_served():
    client = create_app().test_client()
    html = client.get("/").data.decode()
    assert 'rel="icon"' in html
    assert "/static/favicon.svg" in html

    response = client.get("/static/favicon.svg")
    assert response.status_code == 200
    assert response.mimetype == "image/svg+xml"
    assert b"<svg" in response.data


def test_status_endpoint_approves_candidate(monkeypatch):
    from hainan_cycling.web import routes
    from hainan_cycling.catalog.models import Attraction

    calls = []

    def fake_set_status(attraction_id, status):
        calls.append((attraction_id, status))
        return Attraction(id=attraction_id, name="示例", region="海口市", category="coast", status=status)

    monkeypatch.setattr(routes, "set_attraction_status", fake_set_status)
    response = create_app().test_client().post(
        "/api/attractions/sample-place/status", json={"status": "approved"}
    )

    assert response.status_code == 200
    assert response.json["status"] == "approved"
    assert calls == [("sample-place", "approved")]


def test_status_endpoint_rejects_missing_or_invalid_input(monkeypatch):
    from hainan_cycling.web import routes
    from hainan_cycling.catalog.repository import AttractionNotFoundError

    client = create_app().test_client()
    assert client.post("/api/attractions/x/status", json={}).status_code == 400

    def raise_value_error(attraction_id, status):
        raise ValueError("bad status")

    monkeypatch.setattr(routes, "set_attraction_status", raise_value_error)
    assert client.post("/api/attractions/x/status", json={"status": "nope"}).status_code == 400

    def raise_not_found(attraction_id, status):
        raise AttractionNotFoundError(attraction_id)

    monkeypatch.setattr(routes, "set_attraction_status", raise_not_found)
    assert client.post("/api/attractions/x/status", json={"status": "approved"}).status_code == 404


def test_delete_endpoint_removes_candidate(monkeypatch):
    from hainan_cycling.web import routes
    from hainan_cycling.catalog.repository import AttractionNotFoundError

    deleted = []
    monkeypatch.setattr(routes, "delete_attraction", deleted.append)
    client = create_app().test_client()

    assert client.delete("/api/attractions/sample-place").status_code == 204
    assert deleted == ["sample-place"]

    def raise_not_found(attraction_id):
        raise AttractionNotFoundError(attraction_id)

    monkeypatch.setattr(routes, "delete_attraction", raise_not_found)
    assert client.delete("/api/attractions/missing").status_code == 404


def test_static_script_wires_review_actions():
    response = create_app().test_client().get("/static/js/app.js")

    assert b"/status" in response.data
    assert b'method: "DELETE"' in response.data
