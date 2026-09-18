from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from .models import Provenance, RawRate


class ConsensusError(Exception):
    pass


@dataclass
class ConsensusResult:
    median_rate: Decimal
    p25_rate: Decimal | None
    p75_rate: Decimal | None
    sample_size: int
    confidence: float
    quality_score: float
    warnings: list[str]
    provenance: list[Provenance]


def source_weight(source_id: str) -> float:
    """Known publishers are trusted equally; unknown feeds are discounted."""
    return {
        "SRC-FBX-001": 1.0,
        "SRC-WCI-001": 1.0,
        "SRC-SCFI-001": 1.0,
    }.get(source_id, 0.5)


def _quantile(values: list[Decimal], fraction: Decimal) -> Decimal:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * fraction
    lower, upper = int(position), min(int(position) + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def compute_consensus(rates: list[RawRate]) -> ConsensusResult:
    positive = [rate for rate in rates if rate.rate > 0]
    if not positive:
        raise ConsensusError("no positive rates available")
    values = sorted(rate.rate for rate in positive)
    q25, q75 = _quantile(values, Decimal("0.25")), _quantile(values, Decimal("0.75"))
    initial = Decimal(str(median(values)))
    iqr = q75 - q25
    low, high = initial - Decimal("1.5") * iqr, initial + Decimal("1.5") * iqr
    survivors = [rate for rate in positive if low <= rate.rate <= high]
    warnings = [
        f"outlier rejected: {rate.source_id} rate={rate.rate}"
        for rate in positive if rate not in survivors
    ]
    if len(survivors) < 2:
        raise ConsensusError("at least two rates are required after outlier rejection")
    survivor_values = sorted(rate.rate for rate in survivors)
    median_rate = Decimal(str(median(survivor_values)))
    spread = (max(survivor_values) - min(survivor_values)) / median_rate
    confidence = min(Decimal("1"), Decimal(len(survivors)) / Decimal("4")) * (
        Decimal("1") - min(Decimal("0.5"), spread)
    )
    confidence = max(Decimal("0"), confidence)
    provenance = [
        Provenance(source_id=r.source_id, publisher=r.publisher,
                   retrieved_at=r.retrieved_at, source_url=r.source_url)
        for r in survivors
    ]
    return ConsensusResult(
        median_rate=median_rate,
        p25_rate=_quantile(survivor_values, Decimal("0.25")),
        p75_rate=_quantile(survivor_values, Decimal("0.75")),
        sample_size=len(survivors),
        confidence=float(confidence),
        quality_score=float(confidence),
        warnings=warnings,
        provenance=provenance,
    )
