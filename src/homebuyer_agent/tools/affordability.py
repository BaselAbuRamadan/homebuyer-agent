"""Deterministic affordability tools. Plain maths, no AI.

The model decides WHEN to call these; Python does the arithmetic, so numbers are
never made up. Rates and percentages are given in PERCENT (6.5 means 6.5%).

All figures are educational estimates, not financial advice.
"""

# Default assumptions. Every result repeats the ones it used.
DEFAULT_YEARS = 30
DEFAULT_PROPERTY_TAX_RATE_PCT = 1.1   # rough US average; listings carry their own rate
DEFAULT_INSURANCE_ANNUAL = 1800.0
PMI_ANNUAL_RATE_PCT = 0.5             # charged on the loan when down payment < 20%
FRONT_END_RATIO = 0.28                # housing costs <= 28% of gross income (kb_002)
DEFAULT_TARGET_DTI = 0.36             # all debts incl. housing <= 36% of gross income (kb_002)


def _check_range(name: str, value: float, low: float, high: float) -> None:
    """Raise a clear error for impossible inputs instead of returning a wrong number."""
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}, got {value}")


def principal_and_interest(loan: float, annual_rate_pct: float, years: int) -> float:
    """Fixed monthly payment that pays a loan down to exactly zero (amortisation).

    payment = loan * r / (1 - (1 + r) ** -n)
      r = monthly rate (annual % / 100 / 12), n = number of monthly payments.
    Early payments are mostly interest; later ones are mostly principal.
    At a 0% rate there is no interest, so it is simply loan / n.
    """
    n = years * 12
    r = annual_rate_pct / 100 / 12
    if loan <= 0:
        return 0.0
    if r == 0:
        return loan / n
    return loan * r / (1 - (1 + r) ** -n)


def monthly_payment(
    price: float,
    down_payment_pct: float,
    annual_rate: float,
    years: int = DEFAULT_YEARS,
    property_tax_rate: float = DEFAULT_PROPERTY_TAX_RATE_PCT,
    hoa_monthly: float = 0.0,
    insurance_annual: float = DEFAULT_INSURANCE_ANNUAL,
) -> dict:
    """Itemised monthly cost of buying one home.

    Args:
        price: home price in USD.
        down_payment_pct: down payment in percent of price (10 = 10%).
        annual_rate: mortgage interest rate in percent (6.5 = 6.5%).
        years: loan term in years.
        property_tax_rate: yearly property tax in percent of price (2.1 = 2.1%).
        hoa_monthly: HOA dues per month in USD.
        insurance_annual: homeowners insurance per year in USD.

    Returns a dict with each monthly component, the total, and the assumptions used.
    """
    _check_range("price", price, 1, 50_000_000)
    _check_range("down_payment_pct", down_payment_pct, 0, 100)
    _check_range("annual_rate", annual_rate, 0, 25)
    _check_range("years", years, 1, 50)
    _check_range("property_tax_rate", property_tax_rate, 0, 10)
    _check_range("hoa_monthly", hoa_monthly, 0, 10_000)
    _check_range("insurance_annual", insurance_annual, 0, 100_000)

    down_payment = price * down_payment_pct / 100
    loan = price - down_payment
    pi = principal_and_interest(loan, annual_rate, years)
    tax = price * property_tax_rate / 100 / 12
    insurance = insurance_annual / 12
    pmi = loan * PMI_ANNUAL_RATE_PCT / 100 / 12 if down_payment_pct < 20 else 0.0
    total = pi + tax + insurance + hoa_monthly + pmi

    return {
        "price": round(price, 2),
        "down_payment": round(down_payment, 2),
        "loan_amount": round(loan, 2),
        "monthly": {
            "principal_and_interest": round(pi, 2),
            "property_tax": round(tax, 2),
            "insurance": round(insurance, 2),
            "hoa": round(hoa_monthly, 2),
            "pmi": round(pmi, 2),
            "total": round(total, 2),
        },
        "assumptions": {
            "annual_rate_pct": annual_rate,
            "years": years,
            "property_tax_rate_pct": property_tax_rate,
            "insurance_annual": insurance_annual,
            "pmi": f"{PMI_ANNUAL_RATE_PCT}% of the loan per year, only when down payment is under 20%",
            "note": "Educational estimate, not financial advice. Excludes utilities, maintenance and closing costs.",
        },
    }


def max_affordable_price(
    annual_income: float,
    monthly_debts: float,
    down_payment_savings: float,
    annual_rate: float,
    target_dti: float = DEFAULT_TARGET_DTI,
    years: int = DEFAULT_YEARS,
    property_tax_rate: float = DEFAULT_PROPERTY_TAX_RATE_PCT,
    hoa_monthly: float = 0.0,
    insurance_annual: float = DEFAULT_INSURANCE_ANNUAL,
) -> dict:
    """Highest home price whose full monthly cost fits common lender guidelines.

    Step 1, monthly housing budget = the LOWER of:
      - 28% of gross monthly income (housing-only rule), and
      - target_dti (36%) of gross monthly income minus existing debts (all-debts rule).
    Step 2, find the price whose monthly cost (P&I + tax + insurance + HOA + PMI)
      equals that budget. All savings are used as the down payment.

    The monthly cost rises in a straight line with price, so we can solve for the
    price directly instead of guessing. PMI makes it a two-part line (with or
    without PMI), which is handled below.

    Args:
        annual_income: gross yearly household income in USD.
        monthly_debts: existing monthly debt payments in USD (car, cards, loans).
        down_payment_savings: cash available for the down payment in USD.
        annual_rate: mortgage interest rate in percent (6.5 = 6.5%).
        target_dti: maximum share of income for all debts, as a fraction (0.36).
    """
    _check_range("annual_income", annual_income, 0, 100_000_000)
    _check_range("monthly_debts", monthly_debts, 0, 1_000_000)
    _check_range("down_payment_savings", down_payment_savings, 0, 100_000_000)
    _check_range("annual_rate", annual_rate, 0, 25)
    _check_range("target_dti", target_dti, 0.05, 0.6)
    _check_range("years", years, 1, 50)
    _check_range("property_tax_rate", property_tax_rate, 0, 10)
    _check_range("hoa_monthly", hoa_monthly, 0, 10_000)
    _check_range("insurance_annual", insurance_annual, 0, 100_000)

    gross_monthly = annual_income / 12
    front_end_limit = gross_monthly * FRONT_END_RATIO
    back_end_limit = gross_monthly * target_dti - monthly_debts
    budget = min(front_end_limit, back_end_limit)
    binding_rule = "28% housing rule" if front_end_limit <= back_end_limit else f"{target_dti:.0%} total-debt rule"

    fixed = insurance_annual / 12 + hoa_monthly            # costs that don't depend on price
    pi_per_dollar = principal_and_interest(1.0, annual_rate, years)  # P&I for each $1 borrowed
    tax_per_dollar = property_tax_rate / 100 / 12
    pmi_per_dollar = PMI_ANNUAL_RATE_PCT / 100 / 12
    d = down_payment_savings

    if budget <= fixed:
        price = 0.0
    else:
        # Without PMI: budget = (price - d) * pi + price * tax + fixed
        price_no_pmi = (budget - fixed + d * pi_per_dollar) / (pi_per_dollar + tax_per_dollar)
        if d >= 0.2 * price_no_pmi:
            price = price_no_pmi
        else:
            # With PMI: budget = (price - d) * (pi + pmi) + price * tax + fixed
            price_pmi = (budget - fixed + d * (pi_per_dollar + pmi_per_dollar)) / (
                pi_per_dollar + pmi_per_dollar + tax_per_dollar
            )
            # If that lower price would already reach 20% down, PMI wouldn't apply,
            # so the true answer sits exactly at the 20%-down point.
            price = price_pmi if d < 0.2 * price_pmi else d / 0.2
        price = max(price, 0.0)

    down_pct = (d / price * 100) if price > 0 else 0.0
    breakdown = (
        monthly_payment(price, min(down_pct, 100), annual_rate, years, property_tax_rate, hoa_monthly, insurance_annual)
        if price > 0 else None
    )

    return {
        "max_price": round(price, -3) if price >= 1000 else round(price, 2),
        "monthly_housing_budget": round(max(budget, 0.0), 2),
        "limiting_rule": binding_rule,
        "down_payment": round(d, 2),
        "down_payment_pct": round(down_pct, 1),
        "monthly_breakdown_at_max": breakdown["monthly"] if breakdown else None,
        "assumptions": {
            "annual_rate_pct": annual_rate,
            "years": years,
            "front_end_ratio": FRONT_END_RATIO,
            "target_dti": target_dti,
            "property_tax_rate_pct": property_tax_rate,
            "insurance_annual": insurance_annual,
            "hoa_monthly": hoa_monthly,
            "note": (
                "Educational estimate, not financial advice. Uses all savings as the down payment "
                "and sets nothing aside for closing costs (often 2-5% of the price)."
            ),
        },
    }


# JSON schemas the model reads to know how to call these tools (OpenAI function calling).
MONTHLY_PAYMENT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "monthly_payment",
        "description": (
            "Calculate the itemised monthly cost of buying a specific home: principal and interest, "
            "property tax, insurance, HOA and PMI. Use when the user gives a price (or a listing) "
            "and wants to know the monthly payment."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "price": {"type": "number", "description": "Home price in USD."},
                "down_payment_pct": {"type": "number", "description": "Down payment in percent of price, e.g. 10 for 10%."},
                "annual_rate": {"type": "number", "description": "Mortgage interest rate in percent, e.g. 6.5 for 6.5%."},
                "years": {"type": "integer", "description": "Loan term in years. Default 30."},
                "property_tax_rate": {
                    "type": "number",
                    "description": "Yearly property tax in percent of price, e.g. 2.1. Use the listing's rate if known. Default 1.1.",
                },
                "hoa_monthly": {"type": "number", "description": "HOA dues per month in USD. Default 0."},
                "insurance_annual": {"type": "number", "description": "Homeowners insurance per year in USD. Default 1800."},
            },
            "required": ["price", "down_payment_pct", "annual_rate"],
        },
    },
}

MAX_AFFORDABLE_PRICE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "max_affordable_price",
        "description": (
            "Estimate the highest home price a buyer can afford from their income, monthly debts and "
            "savings, using the 28% housing and 36% total-debt guidelines. Use when the user asks "
            "what they can afford or what price range is realistic."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "annual_income": {"type": "number", "description": "Gross yearly household income in USD."},
                "monthly_debts": {"type": "number", "description": "Existing monthly debt payments in USD. Use 0 if none."},
                "down_payment_savings": {"type": "number", "description": "Cash available for the down payment in USD."},
                "annual_rate": {"type": "number", "description": "Mortgage interest rate in percent, e.g. 6.5 for 6.5%."},
                "target_dti": {"type": "number", "description": "Max share of income for all debts, as a fraction. Default 0.36."},
                "property_tax_rate": {"type": "number", "description": "Yearly property tax in percent of price. Default 1.1."},
                "hoa_monthly": {"type": "number", "description": "Expected HOA dues per month in USD. Default 0."},
            },
            "required": ["annual_income", "monthly_debts", "down_payment_savings", "annual_rate"],
        },
    },
}
