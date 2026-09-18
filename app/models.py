from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class FreightRateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: str = Field(..., examples=["CNSHA"])
    destination: str = Field(..., examples=["USLAX"])
    mode: Literal["ocean", "air", "road"] = "ocean"
    container: Literal["20GP", "40GP", "40HC", "45HC"] = "40HC"

    @field_validator("origin", "destination", mode="before")
    @classmethod
    def uppercase(cls, value: str) -> str:
        return str(value).upper()


class RawRate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    publisher: str
    origin: str
    destination: str
    mode: str
    container: str
    rate: Decimal
    currency: str = "USD"
    retrieved_at: datetime
    source_url: str

    _validate_time = field_validator("retrieved_at")(_aware)


class Provenance(BaseModel):
    source_id: str
    publisher: str
    retrieved_at: datetime
    source_url: str
    _validate_time = field_validator("retrieved_at")(_aware)


class Freshness(BaseModel):
    age_seconds: int
    ttl_seconds: int
    stale: bool


class Trust(BaseModel):
    confidence: float = Field(ge=0, le=1)
    quality_score: float = Field(ge=0, le=1)
    verified: bool


class License(BaseModel):
    type: str
    usage: str


class RateLimit(BaseModel):
    limit: int
    window_seconds: int


class ApiMeta(BaseModel):
    latency_ms: int
    rate_limit: RateLimit


class Meta(BaseModel):
    request_id: str
    product_id: str = "logistics.freight.rate.v1"
    version: str = "1.0.0"
    served_at: datetime
    source_last_updated_at: datetime
    freshness: Freshness
    provenance: list[Provenance]
    trust: Trust
    license: License
    api: ApiMeta
    warnings: list[str] = Field(default_factory=list)


class FreightRateData(BaseModel):
    origin: str
    destination: str
    mode: str
    container: str
    median_rate: Decimal
    currency: str
    valid_for: date
    sample_size: int
    p25_rate: Decimal | None
    p75_rate: Decimal | None


class FreightRateResponse(BaseModel):
    data: FreightRateData
    meta: Meta


class ErrorResponse(BaseModel):
    error: str
    error_code: str
    details: str | dict
    request_id: str
    served_at: datetime
