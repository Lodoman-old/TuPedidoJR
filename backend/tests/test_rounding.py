from decimal import Decimal

from app.services.rounding import round_half_down


def test_round_half_down_rule():
    assert round_half_down(Decimal("25.5")) == Decimal("25")
    assert round_half_down(Decimal("25.6")) == Decimal("26")
    assert round_half_down(Decimal("25.4")) == Decimal("25")
    assert round_half_down(Decimal("0.5")) == Decimal("0")
    assert round_half_down(Decimal("0.6")) == Decimal("1")
