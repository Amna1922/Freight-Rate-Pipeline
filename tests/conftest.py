from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models import RawRate


@pytest.fixture
def sample_rates() -> list[RawRate]:
    now = datetime.now(timezone.utc)
    return [
        RawRate(source_id="SRC-FBX-001", publisher="Freightos Baltic Index",
                 origin="CNSHA", destination="USLAX", mode="ocean", container="40HC",
                 rate=Decimal("2200"), retrieved_at=now, source_url="https://example.test/fbx"),
        RawRate(source_id="SRC-WCI-001", publisher="Drewry World Container Index",
                 origin="CNSHA", destination="USLAX", mode="ocean", container="40HC",
                 rate=Decimal("2250"), retrieved_at=now, source_url="https://example.test/wci"),
    ]
