"""API contracts for projects (docs/14 §8)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ProjectCreateRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        # str_strip_whitespace runs first, so a whitespace-only name arrives empty and
        # would otherwise slip past min_length on the raw input.
        if not v.strip():
            raise ValueError("Project name cannot be blank.")
        return v


class ProjectUpdateRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    archived: bool | None = None


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    archived_at: datetime | None = None
    created_at: datetime
    # Denormalized for the switcher and the projects list — the alternative is the
    # client issuing one count query per project.
    session_count: int = 0

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]
    total: int
