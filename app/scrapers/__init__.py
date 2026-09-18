class ScraperError(Exception):
    def __init__(self, source_id: str, reason: str, status_code: int | None = None):
        self.source_id, self.reason, self.status_code = source_id, reason, status_code
        super().__init__(f"{source_id}: {reason}")


from .fbx import fetch_fbx_rates
from .scfi import fetch_scfi_rates
from .wci import fetch_wci_rates

__all__ = ["ScraperError", "fetch_fbx_rates", "fetch_wci_rates", "fetch_scfi_rates"]
