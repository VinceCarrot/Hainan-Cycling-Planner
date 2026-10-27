"""Pydantic request schemas for the local API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

InterestStatus = Literal["undecided", "want_to_visit", "maybe", "skip", "needs_research"]


class DecisionRequest(BaseModel):
    decision: InterestStatus
    score: int | None = Field(default=None, ge=0, le=10)
    reason: str | None = Field(default=None, max_length=500)


class BulkDecisionRequest(BaseModel):
    place_ids: list[int] = Field(min_length=1, max_length=500)
    decision: InterestStatus


class PlaceUpdateRequest(BaseModel):
    personal_notes: str | None = Field(default=None, max_length=5000)
    verification_status: Literal["unverified", "partially_verified", "verified", "disputed"] | None = None
    canonical_name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=50)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be given together")
        return self


class MergeRequest(BaseModel):
    source_id: int
    target_id: int
    reason: str | None = Field(default=None, max_length=300)


class RelationStatusRequest(BaseModel):
    status: Literal["confirmed", "rejected", "pending"]


class ImageAssociationRequest(BaseModel):
    status: Literal["suggested", "user_verified", "rejected"]
    notes: str | None = Field(default=None, max_length=500)
    make_primary: bool | None = None


class ImageReportRequest(BaseModel):
    issue: str = Field(min_length=1, max_length=500)


class JobRequest(BaseModel):
    job_type: Literal[
        "discover_osm", "build_regions", "discover_wikidata", "discover_wikipedia", "build_corridor", "nearby_expansion",
        "images_for_place", "images_batch", "commons_sweep", "download_pending", "research_place", "research_batch", "fetch_url", "web_search",
    ]
    payload: dict = Field(default_factory=dict)
    priority: int = Field(default=5, ge=0, le=10)


class UrlRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)

    @field_validator("url")
    @classmethod
    def _scheme(cls, v: str) -> str:
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v


class ExportRequest(BaseModel):
    format: Literal["csv", "json", "geojson"] = "json"
    interest: list[InterestStatus] | None = None
    include_seeds: bool = False


class RestoreRequest(BaseModel):
    backup_name: str = Field(min_length=1, max_length=200)
