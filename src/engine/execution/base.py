from dataclasses import dataclass

@dataclass
class Order:
    market_id: str
    selection_id: str
    side: str
    price: float
    size: float

class Executor:
    def place(self, order):
        raise NotImplementedError
