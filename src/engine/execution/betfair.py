from ..config import ENABLE_LIVE_EXECUTION

class BetfairExecutor:
    """Disabled until you explicitly flip ENABLE_LIVE_EXECUTION and wire your own account."""
    def __init__(self, client=None):
        self.client = client

    def place(self, order):
        if not ENABLE_LIVE_EXECUTION:
            raise RuntimeError("LIVE EXECUTION IS DISABLED")
        if self.client is None:
            raise RuntimeError("Betfair client not configured")
        raise NotImplementedError("Map Order to venue market/selection IDs before enabling placement")
