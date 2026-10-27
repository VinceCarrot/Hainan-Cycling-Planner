import pytest
import json

from hainan_cycling.catalog import repository


def test_list_attractions_filters_by_review_status(monkeypatch, tmp_path):
    catalog_path = tmp_path / "attractions.json"
    catalog_path.write_text(
        json.dumps(
            [
                {
                    "id": "approved-place",
                    "name": "已审核地点",
                    "region": "海口市",
                    "category": "coast",
                    "status": "approved",
                },
                {
                    "id": "candidate-place",
                    "name": "待审核地点",
                    "region": "文昌市",
                    "category": "village",
                    "status": "candidate",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(repository, "CATALOG_PATH", catalog_path)

    attractions = repository.list_attractions(status="approved")

    assert [attraction.id for attraction in attractions] == ["approved-place"]


def test_list_attractions_sorts_by_counterclockwise_route(monkeypatch, tmp_path):
    catalog_path = tmp_path / "attractions.json"
    catalog_path.write_text(
        json.dumps(
            [
                {
                    "id": "wenchang-place",
                    "name": "文昌地点",
                    "region": "文昌市",
                    "category": "coast",
                },
                {
                    "id": "chengmai-place",
                    "name": "澄迈地点",
                    "region": "澄迈县",
                    "category": "coast",
                },
                {
                    "id": "haikou-place",
                    "name": "海口地点",
                    "region": "海口市",
                    "category": "coast",
                },
                {
                    "id": "another-haikou-place",
                    "name": "海口另一地点",
                    "region": "海口市",
                    "category": "coast",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(repository, "CATALOG_PATH", catalog_path)

    attractions = repository.list_attractions()

    assert [attraction.id for attraction in attractions] == [
        "haikou-place",
        "another-haikou-place",
        "chengmai-place",
        "wenchang-place",
    ]


def test_list_attractions_loads_canonical_catalog_only(monkeypatch, tmp_path):
    catalog_path = tmp_path / "attractions.json"
    catalog_path.write_text(
        json.dumps(
            [
                {
                    "id": "base-place",
                    "name": "基础地点",
                    "region": "海口市",
                    "category": "coast",
                    "status": "candidate",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "attractions_batch_01.json").write_text(
        json.dumps(
            [
                {
                    "id": "batch-place",
                    "name": "批次地点",
                    "region": "文昌市",
                    "category": "coast",
                    "status": "candidate",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(repository, "CATALOG_PATH", catalog_path)

    attractions = repository.list_attractions(status="candidate")

    assert [attraction.id for attraction in attractions] == ["base-place"]


def test_researched_candidate_catalog_loads():
    attractions = repository.list_attractions()

    assert len(attractions) == 128
    assert {attraction.name for attraction in attractions} >= {
        "海口钟楼",
        "万绿园",
        "海口骑楼老街",
        "观海台",
        "铜鼓岭",
        "文昌石头公园",
        "光村银滩",
        "峨蔓火山海岸地质公园",
        "东郊椰林风景区",
        "五指山景区",
        "五公祠",
        "日月湾",
        "文昌孔庙",
        "万宁山钦湾·燕子洞",
        "海南疍家博物馆",
        "棋子湾小角公园",
        "尖峰岭雨林谷",
        "东方白查村船形屋",
        "五指山市三月三广场",
        "临高金牌湾小渔村",
        "东方风车海岸",
        "儋州红树林石趣观景台",
        "儋州珍珠湾观景台",
        "儋州龙腾云霞观景台",
        "万宁兴隆巴厘村",
        "保亭七仙岭温泉国家森林公园",
        "陵水富力海洋欢乐世界",
        "琼海红石滩",
        "琼海潭门港",
        "琼海潭门排港村海边任意门",
        "陵水岭仔湾",
        "澄迈福山咖啡文化风情镇",
        "澄迈保良古村",
        "临高古银瀑布",
        "昌江霸王岭路边观景台",
        "陵水红角岭海岸观景台",
        "万宁赤村后海沙滩",
        "屯昌雷公滩红石河谷",
        "屯昌木色湖",
        "屯昌美鹤园竹林",
        "海口假日海滩",
        "陵水虎岭与尖岭海岸",
        "昌江棋子湾玻璃海公路",
        "昌江7号彩虹公路驿站",
        "三亚海棠河公园骑行绿道",
        "临高东英国际慢城赶海公园",
    }
    assert {attraction.status for attraction in attractions} <= {
        "candidate",
        "under_review",
        "approved",
        "rejected",
    }
    assert len({attraction.id for attraction in attractions}) == 128
    assert sum(attraction.latitude is not None for attraction in attractions) == 32
    lingao_cape = next(
        attraction
        for attraction in attractions
        if attraction.id == "lingao-cape-scenic-area"
    )
    assert "xiaohongshu-lingao-cape-cycling-2026" in (
        lingao_cape.summary.source_ids
    )
    windmill_coast = next(
        attraction
        for attraction in attractions
        if attraction.id == "dongfang-windmill-coast"
    )
    assert "xiaohongshu-dongfang-windmill-coast-ride-2025" in (
        windmill_coast.summary.source_ids
    )
    assert any(
        str(source.url)
        == "https://www.xiaohongshu.com/explore/6ad600460000000029018a70"
        for source in windmill_coast.sources
    )
    haihua_island = next(
        attraction for attraction in attractions if attraction.id == "danzhou-ocean-flower-island"
    )
    assert haihua_island.summary is not None
    assert "xiaohongshu-danzhou-day3-haihua-haitou" in (
        haihua_island.summary.source_ids
    )
    assert any(
        str(source.url)
        == "https://www.xiaohongshu.com/explore/6960c614000000000c03786e"
        for source in haihua_island.sources
    )
    yinggehai = next(
        attraction for attraction in attractions if attraction.id == "ledong-yinggehai-town"
    )
    assert yinggehai.summary is not None
    assert "xiaohongshu-ledong-yinggehai-road-advice" in (
        yinggehai.summary.source_ids
    )
    assert any(
        str(source.url)
        == "https://www.xiaohongshu.com/explore/697770bc000000001a0213ab"
        for source in yinggehai.sources
    )
    researched_note_attractions = (
        "lingao-cape-scenic-area",
        "lingao-dongying-international-slow-city-tidal-flat-park",
        "danzhou-guangcun-silver-beach",
        "danzhou-longmen-jilang",
        "danzhou-longteng-yunxia-viewpoint",
    )
    for attraction_id in researched_note_attractions:
        attraction = next(
            item for item in attractions if item.id == attraction_id
        )
        assert attraction.summary is not None
        assert "xiaohongshu-lingao-danzhou-selfdrive-2026" in (
            attraction.summary.source_ids
        )
        assert any(
            str(source.url)
            == "https://www.xiaohongshu.com/explore/6ac1290e000000001a02065c"
            for source in attraction.sources
        )
    for attraction_id in (
        "lingao-cape-scenic-area",
        "danzhou-guangcun-silver-beach",
        "danzhou-longmen-jilang",
    ):
        attraction = next(
            item for item in attractions if item.id == attraction_id
        )
        assert attraction.summary is not None
        assert "xiaohongshu-nanshan-day1-haihua-island" in (
            attraction.summary.source_ids
        )
        assert any(
            str(source.url)
            == "https://www.xiaohongshu.com/explore/694ea8f0000000001e0000e5"
            for source in attraction.sources
        )
    for attraction_id in (
        "changjiang-qizi-bay-glass-sea-road",
        "changjiang-7th-rainbow-road-rest-stop",
        "sanya-haitang-river-park-greenway",
    ):
        attraction = next(
            item for item in attractions if item.id == attraction_id
        )
        assert attraction.summary is not None
        expected_source = (
            "xiaohongshu-sanya-haitang-river-greenway"
            if attraction_id == "sanya-haitang-river-park-greenway"
            else "xiaohongshu-qizi-bay-to-dongfang-ride-2025"
        )
        expected_url = (
            "https://www.xiaohongshu.com/explore/695df27b000000002103d343"
            if attraction_id == "sanya-haitang-river-park-greenway"
            else "https://www.xiaohongshu.com/explore/6953ce4500000000210303eb"
        )
        assert expected_source in attraction.summary.source_ids
        assert any(str(source.url) == expected_url for source in attraction.sources)


def test_canonical_catalog_is_stored_in_route_order():
    with repository.CATALOG_PATH.open(encoding="utf-8") as catalog_file:
        records = json.load(catalog_file)

    region_order = {
        region: index for index, region in enumerate(repository.REGION_ROUTE_ORDER)
    }
    region_indexes = [region_order[record["region"]] for record in records]

    assert region_indexes == sorted(region_indexes)


def test_swallow_cave_includes_inspected_xiaohongshu_route_notes():
    attraction = next(
        item
        for item in repository.list_attractions()
        if item.id == "wanning-shanqin-bay-swallow-cave"
    )

    assert attraction.summary is not None
    assert "约500米沙滩路" in attraction.summary.text
    assert [source.id for source in attraction.sources] == [
        "xiaohongshu-swallow-cave-cycling-2026"
    ]


def test_bawangling_viewpoint_merges_notes_for_same_roadside_stop():
    attraction = next(
        item
        for item in repository.list_attractions()
        if item.id == "changjiang-bawangling-roadside-viewpoint"
    )

    assert attraction.summary is not None
    assert "705县道" in attraction.summary.text
    assert len(attraction.sources) == 2


def _write_catalog(path, records):
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


SAMPLE_RECORDS = [
    {
        "id": "haikou-place",
        "name": "海口地点",
        "region": "海口市",
        "category": "coast",
        "status": "candidate",
    },
    {
        "id": "wenchang-place",
        "name": "文昌地点",
        "region": "文昌市",
        "category": "coast",
        "status": "candidate",
    },
]


def test_set_attraction_status_persists_approval(monkeypatch, tmp_path):
    catalog_path = tmp_path / "attractions.json"
    _write_catalog(catalog_path, SAMPLE_RECORDS)
    monkeypatch.setattr(repository, "CATALOG_PATH", catalog_path)

    updated = repository.set_attraction_status("haikou-place", "approved")

    assert updated.status == "approved"
    assert [a.id for a in repository.list_attractions(status="approved")] == ["haikou-place"]
    assert [a.id for a in repository.list_attractions(status="candidate")] == ["wenchang-place"]


def test_set_attraction_status_keeps_catalog_file_style(monkeypatch, tmp_path):
    catalog_path = tmp_path / "attractions.json"
    _write_catalog(catalog_path, SAMPLE_RECORDS)
    monkeypatch.setattr(repository, "CATALOG_PATH", catalog_path)

    repository.set_attraction_status("wenchang-place", "approved")

    raw = catalog_path.read_bytes()
    assert raw.startswith(b"[\r\n    {\r\n")
    assert not raw.endswith(b"\n")
    assert "海口地点".encode() in raw
    assert not (tmp_path / "attractions.json.tmp").exists()
    assert [record["id"] for record in json.loads(raw)] == ["haikou-place", "wenchang-place"]


def test_set_attraction_status_rejects_unknown_id_and_status(monkeypatch, tmp_path):
    catalog_path = tmp_path / "attractions.json"
    _write_catalog(catalog_path, SAMPLE_RECORDS)
    monkeypatch.setattr(repository, "CATALOG_PATH", catalog_path)

    with pytest.raises(repository.AttractionNotFoundError):
        repository.set_attraction_status("missing-place", "approved")
    with pytest.raises(ValueError):
        repository.set_attraction_status("haikou-place", "published")

    assert all(a.status == "candidate" for a in repository.list_attractions())


def test_delete_attraction_removes_record(monkeypatch, tmp_path):
    catalog_path = tmp_path / "attractions.json"
    _write_catalog(catalog_path, SAMPLE_RECORDS)
    monkeypatch.setattr(repository, "CATALOG_PATH", catalog_path)

    repository.delete_attraction("haikou-place")

    assert [a.id for a in repository.list_attractions()] == ["wenchang-place"]
    with pytest.raises(repository.AttractionNotFoundError):
        repository.delete_attraction("haikou-place")
