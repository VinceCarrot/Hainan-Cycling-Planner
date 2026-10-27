from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ReviewStatus(StrEnum):
    CANDIDATE = "candidate"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class SourceKind(StrEnum):
    VISITOR_EXPERIENCE = "visitor_experience"
    OBJECTIVE_REFERENCE = "objective_reference"


class ImageRights(StrEnum):
    LINK_ONLY = "link_only"
    EMBED_ALLOWED = "embed_allowed"
    DOWNLOAD_AUTHORIZED = "download_authorized"
    USER_UPLOADED = "user_uploaded"


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class EvidenceSource(CatalogModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    platform: str = Field(min_length=1)
    kind: SourceKind
    title: str = Field(min_length=1)
    url: HttpUrl
    author: str | None = None
    published_at: date | None = None
    accessed_at: date
    notes: str | None = None


class ExperienceClaim(CatalogModel):
    text: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)


class AttractionImage(CatalogModel):
    source_id: str
    source_url: HttpUrl
    rights: ImageRights
    local_path: str | None = None
    creator: str | None = None
    license_name: str | None = None
    license_url: HttpUrl | None = None
    caption: str | None = None

    @model_validator(mode="after")
    def validate_local_copy_rights(self) -> Self:
        if self.local_path and self.rights not in {
            ImageRights.DOWNLOAD_AUTHORIZED,
            ImageRights.USER_UPLOADED,
        }:
            raise ValueError(
                "A local image copy requires download authorization or user upload"
            )
        if self.local_path and self.rights == ImageRights.DOWNLOAD_AUTHORIZED:
            if not self.creator or not self.license_name or not self.license_url:
                raise ValueError(
                    "A licensed local image requires creator and license attribution"
                )
        return self


class Attraction(CatalogModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1)
    region: str = Field(min_length=1)
    category: str = Field(min_length=1)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    coordinate_source_id: str | None = None
    summary: ExperienceClaim | None = None
    highlights: list[ExperienceClaim] = Field(default_factory=list)
    drawbacks: list[ExperienceClaim] = Field(default_factory=list)
    sources: list[EvidenceSource] = Field(default_factory=list)
    images: list[AttractionImage] = Field(default_factory=list)
    status: ReviewStatus = ReviewStatus.CANDIDATE
    research_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must either both be set or both be empty")

        if (self.latitude is not None) != (self.coordinate_source_id is not None):
            raise ValueError("Coordinates require a coordinate source reference")

        source_ids = {source.id for source in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("Source IDs must be unique within an attraction")

        source_by_id = {source.id: source for source in self.sources}
        if self.coordinate_source_id and self.coordinate_source_id not in source_by_id:
            raise ValueError("Coordinates reference an unknown source ID")
        if self.coordinate_source_id and (
            source_by_id[self.coordinate_source_id].kind
            != SourceKind.OBJECTIVE_REFERENCE
        ):
            raise ValueError("Coordinates must reference an objective data source")

        claims = [*self.highlights, *self.drawbacks]
        if self.summary is not None:
            claims.append(self.summary)
        referenced_ids = {
            source_id
            for claim in claims
            for source_id in claim.source_ids
        }
        referenced_ids.update(image.source_id for image in self.images)
        missing_ids = referenced_ids - source_ids
        if missing_ids:
            raise ValueError(
                "Claims and images reference unknown source IDs: "
                f"{sorted(missing_ids)}"
            )

        visitor_source_ids = {
            source.id
            for source in self.sources
            if source.kind == SourceKind.VISITOR_EXPERIENCE
        }
        non_visitor_claim_ids = {
            source_id
            for claim in claims
            for source_id in claim.source_ids
            if source_id not in visitor_source_ids
        }
        if non_visitor_claim_ids:
            raise ValueError(
                "Experience claims must reference visitor experience sources: "
                f"{sorted(non_visitor_claim_ids)}"
            )
        return self
