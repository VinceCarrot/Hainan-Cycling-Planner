import pytest
from pydantic import ValidationError

from hainan_cycling.catalog.models import (
    Attraction,
    AttractionImage,
    EvidenceSource,
    ImageRights,
    SourceKind,
)


def test_attraction_rejects_incomplete_coordinates():
    with pytest.raises(ValidationError, match="both be set or both be empty"):
        Attraction(
            id="sample-place",
            name="示例地点",
            region="海口",
            category="coast",
            latitude=20.0,
        )


def test_attraction_rejects_claim_without_source():
    with pytest.raises(ValidationError, match="unknown source IDs"):
        Attraction(
            id="sample-place",
            name="示例地点",
            region="海口",
            category="coast",
            highlights=[{"text": "示例体验", "source_ids": ["missing-source"]}],
        )


def test_image_cannot_be_saved_without_explicit_rights():
    with pytest.raises(ValidationError, match="requires download authorization"):
        AttractionImage(
            source_id="visitor-post",
            source_url="https://example.com/post",
            rights=ImageRights.LINK_ONLY,
            local_path="data/media/image.jpg",
        )


def test_coordinates_require_an_objective_source():
    visitor_source = EvidenceSource(
        id="visitor-post",
        platform="bilibili",
        kind=SourceKind.VISITOR_EXPERIENCE,
        title="游客骑行记录",
        url="https://example.com/post",
        accessed_at="2026-10-22",
    )

    with pytest.raises(ValidationError, match="objective data source"):
        Attraction(
            id="sample-place",
            name="示例地点",
            region="海口",
            category="coast",
            latitude=20.0,
            longitude=110.0,
            coordinate_source_id="visitor-post",
            sources=[visitor_source],
        )


def test_coordinates_must_name_their_source():
    with pytest.raises(ValidationError, match="require a coordinate source reference"):
        Attraction(
            id="sample-place",
            name="示例地点",
            region="海口",
            category="coast",
            latitude=20.0,
            longitude=110.0,
        )
