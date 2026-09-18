from decimal import Decimal

from app.consensus import compute_consensus
from app.models import FreightRateRequest
from app.consensus import source_weight


def test_request_normalizes_lane(sample_rates):
    request = FreightRateRequest(origin="cnsha", destination="uslax")
    assert request.origin == "CNSHA"
    assert request.container == "40HC"


def test_consensus_rejects_outlier(sample_rates):
    outlier = sample_rates[0].model_copy(update={"rate": Decimal("9000")})
    result = compute_consensus(sample_rates + [outlier])
    assert result.median_rate == Decimal("2225")
    assert result.warnings


def test_scfi_source_has_full_weight():
    assert source_weight("SRC-SCFI-001") == 1.0
