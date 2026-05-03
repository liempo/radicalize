from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$"


class _Identified(BaseModel):
    id: str = Field(..., min_length=1, pattern=ID_PATTERN)
    name: Optional[str] = None


class GoogleUpstream(_Identified):
    source: Literal["google"] = "google"
    google_calendar_id: str = "primary"


class IcsUpstream(_Identified):
    source: Literal["ics"] = "ics"
    external_ics_url: str = Field(..., min_length=1)


Upstream = Annotated[
    Union[GoogleUpstream, IcsUpstream],
    Field(discriminator="source"),
]


class Downstream(_Identified):
    href: Optional[str] = None
    sync_interval_seconds: Optional[int] = Field(default=None, ge=1)


PairMethod = Literal["replace", "update"]


class Pair(BaseModel):
    upstream_id: str = Field(..., min_length=1, pattern=ID_PATTERN)
    downstream_id: str = Field(..., min_length=1, pattern=ID_PATTERN)
    method: PairMethod = "update"


class PairFile(BaseModel):
    pairs: list[Pair] = Field(default_factory=list)


def display_name(obj: _Identified) -> str:
    return obj.name if (obj.name and obj.name.strip()) else obj.id


def collection_href(downstream: Downstream) -> str:
    return downstream.href if (downstream.href and downstream.href.strip()) else downstream.id
