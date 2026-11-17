"""Grow data/listings.json from the 32 hand-written homes to 160, reproducibly.

Why: with only 8 homes per metro, many reasonable searches ("3-bed in Kyle under
$350k", "step-free entry under $400k") found nothing. This adds 32 homes per metro.

How:
- The original 32 homes (L001-L032) are kept unchanged: tests and eval cases use them.
- New homes follow the same rules as the originals: each metro keeps its own tax
  rate and price-per-square-foot range, and sizes match the bedroom count.
- A fixed random seed means running this again gives exactly the same file.

Run:  python scripts/generate_listings.py
"""
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LISTINGS_PATH = ROOT / "data" / "listings.json"
ORIGINAL_COUNT = 32
NEW_PER_METRO = 32
SEED = 2026

# Per metro: cities (the original four plus two more), tax rate (same as the originals),
# price per square foot range, and HOA dues to choose from.
METROS = {
    "Austin, TX": {"cities": ["Georgetown", "Kyle", "Leander", "Pflugerville", "Hutto", "Liberty Hill"],
                   "tax": 0.021, "ppsf": (180, 245), "hoa": [0, 45, 65, 85, 110, 150]},
    "Dallas, TX": {"cities": ["Celina", "Forney", "Frisco", "Prosper", "McKinney", "Little Elm"],
                   "tax": 0.022, "ppsf": (175, 235), "hoa": [0, 45, 65, 85, 150]},
    "Phoenix, AZ": {"cities": ["Buckeye", "Gilbert", "Queen Creek", "Surprise", "Goodyear", "Mesa"],
                    "tax": 0.0065, "ppsf": (175, 240), "hoa": [0, 85, 110, 150]},
    "Raleigh, NC": {"cities": ["Apex", "Fuquay-Varina", "Knightdale", "Wake Forest", "Holly Springs", "Wendell"],
                    "tax": 0.0095, "ppsf": (170, 230), "hoa": [0, 45, 65, 85, 110, 150]},
}
# Outer "value" towns are cheaper per square foot, sought-after suburbs pricier (1.0 = metro average).
CITY_PRICE_FACTOR = {"Kyle": 0.85, "Hutto": 0.85, "Forney": 0.85, "Buckeye": 0.85, "Wendell": 0.85,
                     "Knightdale": 0.9, "Frisco": 1.08, "Prosper": 1.08, "Gilbert": 1.08, "Apex": 1.08}
BUILDERS = ["Bluebonnet Homes", "Cedar & Main Builders", "Oakline Residential", "Prairie Stone Homes",
            "Saguaro Ridge Builders"]
COMMUNITY_NAMES = ["Brookfield Commons", "Canyon View", "Cypress Hollow", "Harvest Point", "Juniper Trails",
                   "Magnolia Park", "Meadowlark", "Red Oak Crossing", "Silver Sage", "Stonebridge", "Sunset Mesa",
                   "Willow Creek", "Amber Fields", "Lantern Hill", "Heron Lake", "Copper Leaf", "Prairie Glen",
                   "Bluebird Meadows", "Aspen Ridge", "Sycamore Bend", "Larkspur Landing", "Golden Bluff"]
PLAN_NAMES = ["The Aspen", "The Birch", "The Hawthorn", "The Laurel", "The Maple", "The Sequoia", "The Willow",
              "The Cypress", "The Juniper", "The Sage", "The Linden", "The Magnolia"]

# Bedrooms -> (how many of the 32 new homes per metro, square-foot range, bathroom options)
BEDROOMS = {2: (6, (1050, 1450), [2]),
            3: (11, (1450, 2050), [2, 2.5]),
            4: (10, (1950, 2650), [2.5, 3]),
            5: (5, (2500, 3300), [3, 3.5, 4])}
# Per metro, this many homes of each size are ENTRY-LEVEL plans in the cheaper outer towns
# (smaller plan, lower price per square foot), so larger families on a tighter budget
# still find something, as they would in a real market.
ENTRY_LEVEL = {3: 2, 4: 3, 5: 2}
STATUSES = [("move_in_ready", 0.38), ("under_construction", 0.30), ("to_be_built", 0.32)]
COMPLETION_MONTHS = {"under_construction": ["2026-12", "2027-01", "2027-02", "2027-03", "2027-04", "2027-05"],
                     "to_be_built": ["2027-04", "2027-06", "2027-08", "2027-09", "2027-10", "2027-12"]}
GENERAL_FEATURES = ["community pool", "trail access", "home office", "covered patio", "fenced yard",
                    "open kitchen island", "walk-in pantry", "energy-efficient HVAC", "solar-ready",
                    "EV charger pre-wire", "smart home package", "game room", "cul-de-sac lot"]
INCENTIVES = [(None, 0.35),
              ("Rate buydown to 4.99% for first year with preferred lender", 0.20),
              ("Up to $10,000 toward closing costs with preferred lender", 0.18),
              ("Free upgraded appliance package", 0.15),
              ("$5,000 off base price on move-in ready homes", 0.12)]


def weighted(rng: random.Random, options: list[tuple]) -> object:
    values, weights = zip(*options)
    return rng.choices(values, weights=weights, k=1)[0]


def features_for(rng: random.Random, beds: int) -> list[str]:
    """3-6 features. Smaller homes are often single-storey; some of those are step-free."""
    chosen = rng.sample(GENERAL_FEATURES, k=rng.randint(2, 4))
    garage = "three-car garage" if beds >= 4 and rng.random() < 0.5 else "two-car garage"
    if rng.random() < 0.75:
        chosen.append(garage)
    single_storey_chance = {2: 0.55, 3: 0.45, 4: 0.15, 5: 0.0}[beds]
    if rng.random() < single_storey_chance:
        chosen.append("single-storey")
        if rng.random() < 0.55:
            chosen.append("step-free entry")
        if rng.random() < 0.30:
            chosen.append("wide doorways")
        if rng.random() < 0.25:
            chosen.append("accessible primary suite")
    return chosen


def lower_part(low: float, high: float, share: float = 0.4) -> tuple[float, float]:
    """The cheapest `share` of a range, e.g. the smallest 40% of plan sizes."""
    return low, low + (high - low) * share


def new_listing(rng: random.Random, listing_id: str, metro: str, beds: int, entry_level: bool = False) -> dict:
    config = METROS[metro]
    count, (sqft_low, sqft_high), bath_options = BEDROOMS[beds]
    if entry_level:
        value_towns = [c for c in config["cities"] if CITY_PRICE_FACTOR.get(c, 1.0) < 1.0]
        city = rng.choice(value_towns)
        sqft = rng.randint(*map(int, lower_part(sqft_low, sqft_high)))
        ppsf = rng.uniform(*lower_part(*config["ppsf"]))
    else:
        city = rng.choice(config["cities"])
        sqft = rng.randint(sqft_low, sqft_high)
        ppsf = rng.uniform(*config["ppsf"])
    price = round(sqft * ppsf * CITY_PRICE_FACTOR.get(city, 1.0), -3)
    status = weighted(rng, STATUSES)
    incentive = weighted(rng, INCENTIVES)
    if incentive and "move-in ready" in incentive and status != "move_in_ready":
        incentive = None                       # that incentive only applies to finished homes
    return {
        "id": listing_id,
        "community": f"{rng.choice(COMMUNITY_NAMES)} at {city}",
        "builder": rng.choice(BUILDERS),
        "city": city,
        "metro": metro,
        "plan_name": rng.choice(PLAN_NAMES),
        "price_usd": int(price),
        "beds": beds,
        "baths": rng.choice(bath_options),
        "sqft": sqft,
        "status": status,
        "est_completion": rng.choice(COMPLETION_MONTHS[status]) if status != "move_in_ready" else None,
        "hoa_monthly_usd": rng.choice(config["hoa"]),
        "est_property_tax_rate": config["tax"],
        "features": features_for(rng, beds),
        "builder_incentive": incentive,
    }


def main() -> None:
    data = json.loads(LISTINGS_PATH.read_text(encoding="utf-8"))
    originals = [l for l in data["listings"] if int(l["id"][1:]) <= ORIGINAL_COUNT]
    assert len(originals) == ORIGINAL_COUNT, "the 32 original homes must be present"

    rng = random.Random(SEED)
    plan = [(metro, beds, n < ENTRY_LEVEL.get(beds, 0))
            for metro in METROS for beds, (count, _, _) in BEDROOMS.items() for n in range(count)]
    rng.shuffle(plan)                          # mix metros and sizes through the id range
    new = [new_listing(rng, f"L{ORIGINAL_COUNT + i + 1:03d}", metro, beds, entry_level)
           for i, (metro, beds, entry_level) in enumerate(plan)]

    data["_note"] = ("Sample demo data. Builders, communities and prices are invented for a portfolio project "
                     "and do not represent real listings. L001-L032 were written by hand; L033 onwards were "
                     "generated by scripts/generate_listings.py.")
    data["listings"] = originals + new
    LISTINGS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(data['listings'])} listings ({len(originals)} original + {len(new)} generated) "
          f"to {LISTINGS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
