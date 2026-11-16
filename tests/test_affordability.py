"""Tests for the affordability tools. Pure maths: no API calls."""
import pytest

from homebuyer_agent.tools.affordability import (
    max_affordable_price,
    monthly_payment,
    principal_and_interest,
)


# ---------- principal_and_interest (the amortisation formula) ----------

def test_known_payment_30_years():
    # $360k loan at 6.5% for 30 years = $2,275.44 (matches standard online calculators)
    assert principal_and_interest(360_000, 6.5, 30) == pytest.approx(2275.44, abs=0.01)


def test_known_payment_15_years():
    assert principal_and_interest(400_000, 7.0, 15) == pytest.approx(3595.31, abs=0.01)


def test_zero_rate_is_loan_divided_by_months():
    assert principal_and_interest(360_000, 0, 30) == pytest.approx(1000.0)


def test_no_loan_means_no_payment():
    assert principal_and_interest(0, 6.5, 30) == 0.0


# ---------- monthly_payment ----------

def test_itemised_breakdown_adds_up():
    result = monthly_payment(400_000, 10, 6.5, property_tax_rate=2.0, hoa_monthly=50)
    m = result["monthly"]
    assert result["loan_amount"] == 360_000
    assert m["principal_and_interest"] == pytest.approx(2275.44, abs=0.01)
    assert m["property_tax"] == pytest.approx(666.67, abs=0.01)    # 400k * 2% / 12
    assert m["insurance"] == pytest.approx(150.0)                  # 1800 / 12
    assert m["pmi"] == pytest.approx(150.0)                        # 360k * 0.5% / 12
    assert m["hoa"] == 50
    parts = m["principal_and_interest"] + m["property_tax"] + m["insurance"] + m["pmi"] + m["hoa"]
    assert m["total"] == pytest.approx(parts, abs=0.02)


def test_no_pmi_at_20_percent_down():
    assert monthly_payment(400_000, 20, 6.5)["monthly"]["pmi"] == 0.0


def test_pmi_just_under_20_percent_down():
    assert monthly_payment(400_000, 19.9, 6.5)["monthly"]["pmi"] > 0


def test_zero_percent_down_borrows_full_price_with_pmi():
    result = monthly_payment(300_000, 0, 6.5)
    assert result["loan_amount"] == 300_000
    assert result["down_payment"] == 0
    assert result["monthly"]["pmi"] == pytest.approx(125.0)        # 300k * 0.5% / 12


def test_full_cash_purchase_has_no_loan_costs():
    m = monthly_payment(300_000, 100, 6.5)["monthly"]
    assert m["principal_and_interest"] == 0.0
    assert m["pmi"] == 0.0


def test_assumptions_are_reported():
    assumptions = monthly_payment(400_000, 10, 6.5)["assumptions"]
    assert assumptions["annual_rate_pct"] == 6.5
    assert assumptions["insurance_annual"] == 1800
    assert "not financial advice" in assumptions["note"]


@pytest.mark.parametrize("kwargs", [
    {"price": -1, "down_payment_pct": 10, "annual_rate": 6.5},
    {"price": 400_000, "down_payment_pct": 120, "annual_rate": 6.5},
    {"price": 400_000, "down_payment_pct": 10, "annual_rate": 65},   # someone typed 65 instead of 6.5
])
def test_impossible_inputs_raise_clear_error(kwargs):
    with pytest.raises(ValueError):
        monthly_payment(**kwargs)


# ---------- max_affordable_price ----------

def test_cost_at_max_price_equals_budget():
    # The answer should spend exactly the monthly budget, no more, no less.
    result = max_affordable_price(95_000, 400, 40_000, 6.5)
    assert result["monthly_breakdown_at_max"]["total"] == pytest.approx(result["monthly_housing_budget"], abs=1)
    assert result["max_price"] == pytest.approx(305_000, abs=1_000)


def test_28_percent_rule_limits_low_debt_buyer():
    # 95k/yr: 28% = 2,216.67/month; 36% minus 400 debts = 2,450 -> the 28% rule is lower
    result = max_affordable_price(95_000, 400, 40_000, 6.5)
    assert result["limiting_rule"] == "28% housing rule"
    assert result["monthly_housing_budget"] == pytest.approx(2216.67, abs=0.01)


def test_debt_rule_limits_high_debt_buyer():
    # 95k/yr with 1,500 debts: 36% - 1,500 = 1,350 < 2,216.67
    result = max_affordable_price(95_000, 1_500, 40_000, 6.5)
    assert "total-debt" in result["limiting_rule"]
    assert result["monthly_housing_budget"] == pytest.approx(1350.0, abs=0.01)


def test_more_debt_means_lower_price():
    low_debt = max_affordable_price(95_000, 0, 40_000, 6.5)["max_price"]
    high_debt = max_affordable_price(95_000, 1_500, 40_000, 6.5)["max_price"]
    assert high_debt < low_debt


def test_higher_rate_means_lower_price():
    assert max_affordable_price(95_000, 400, 40_000, 7.5)["max_price"] < max_affordable_price(95_000, 400, 40_000, 5.5)["max_price"]


def test_debts_too_high_gives_zero_not_negative():
    assert max_affordable_price(30_000, 2_000, 5_000, 6.5)["max_price"] == 0


def test_large_savings_means_no_pmi():
    result = max_affordable_price(100_000, 0, 200_000, 6.5)
    assert result["down_payment_pct"] >= 20
    assert result["monthly_breakdown_at_max"]["pmi"] == 0


def test_pmi_boundary_lands_exactly_on_20_percent_down():
    # With 71k savings, PMI would push the price below the 20%-down line, but without
    # PMI the price is above it. The honest answer is exactly 71k / 0.2 = 355k.
    result = max_affordable_price(100_000, 0, 71_000, 6.5)
    assert result["max_price"] == pytest.approx(355_000, abs=1_000)
    assert result["down_payment_pct"] == pytest.approx(20.0, abs=0.1)
    assert result["monthly_breakdown_at_max"]["pmi"] == 0


def test_zero_savings_still_works():
    result = max_affordable_price(95_000, 400, 0, 6.5)
    assert result["max_price"] > 0
    assert result["down_payment_pct"] == 0
