
import os
import re
import json
import httpx

from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

load_dotenv()

TIMEZONE = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Month name → number mapping (for natural-language date parsing)
# ---------------------------------------------------------------------------
MONTH_NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# Known region names (lower-cased for matching)
KNOWN_REGIONS = {"north", "south", "east", "west", "central"}


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------
class QuestionRequest(BaseModel):
    question: str


# ---------------------------------------------------------------------------
# URL builder — injects ?path= into the existing LEDGER_API_URL
# ---------------------------------------------------------------------------
def build_endpoint(path: str) -> str:
    base_url = os.getenv("LEDGER_API_URL")
    if not base_url:
        raise ValueError("LEDGER_API_URL is missing from .env")
    parsed = urlparse(base_url)
    params = parse_qs(parsed.query)
    params["path"] = [path]
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        urlencode(params, doseq=True),
        parsed.fragment,
    ))


# ---------------------------------------------------------------------------
# Timestamp parser — always returns a timezone-aware datetime
# ---------------------------------------------------------------------------
def parse_timestamp(value: str) -> datetime:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=TIMEZONE)
    return ts


def to_kolkata(ts: datetime) -> datetime:
    """Convert any timezone-aware datetime to Asia/Kolkata."""
    return ts.astimezone(TIMEZONE)


# ---------------------------------------------------------------------------
# Data fetching & deduplication
# ---------------------------------------------------------------------------
def load_ledger_data():
    with httpx.Client(timeout=60) as client:
        # Download order records (NDJSON)
        response = client.get(build_endpoint("/export"))
        response.raise_for_status()
        orders = [
            json.loads(line)
            for line in response.text.splitlines()
            if line.strip()
        ]

        # Download exchange rates
        response = client.get(build_endpoint("/rates"))
        response.raise_for_status()
        rates = response.json()["usd_per_unit"]

    # Keep the latest version of each order ID
    latest_orders: dict = {}
    for order in orders:
        oid = order["id"]
        if (
            oid not in latest_orders
            or parse_timestamp(order["updated_at"])
            > parse_timestamp(latest_orders[oid]["updated_at"])
        ):
            latest_orders[oid] = order

    return list(latest_orders.values()), rates


# ---------------------------------------------------------------------------
# Pre-computation — runs once at startup
# ---------------------------------------------------------------------------
def precompute(orders: list, rates: dict) -> dict:
    """
    Build all aggregation tables once so every request is a fast lookup.
    All monetary values are in USD. Date comparisons use Asia/Kolkata.
    Only 'paid' orders count toward revenue / qty.
    'refunded' orders are tracked separately.
    'void' orders are ignored in all calculations.
    """
    paid = [o for o in orders if o["status"] == "paid"]
    refunded = [o for o in orders if o["status"] == "refunded"]

    def usd(order):
        return order["amount"] * rates[order["currency"]]

    def kolkata_month(order):
        return to_kolkata(parse_timestamp(order["created_at"]))

    # ---- Global aggregates ----
    total_revenue = sum(usd(o) for o in paid)
    total_refunds = sum(usd(o) for o in refunded)

    # ---- Product aggregates (paid only) ----
    product_revenue: dict[str, float] = defaultdict(float)
    product_qty: dict[str, int] = defaultdict(int)
    for o in paid:
        product_revenue[o["product"]] += usd(o)
        product_qty[o["product"]] += o["qty"]

    # ---- Region aggregates (paid only) ----
    region_revenue: dict[str, float] = defaultdict(float)
    region_qty: dict[str, int] = defaultdict(int)
    region_orders: dict[str, int] = defaultdict(int)
    for o in paid:
        r = o["region"].lower()
        region_revenue[r] += usd(o)
        region_qty[r] += o["qty"]
        region_orders[r] += 1

    # ---- Customer aggregates (paid only) ----
    customer_spend: dict[str, float] = defaultdict(float)
    customer_orders: dict[str, int] = defaultdict(int)
    for o in paid:
        customer_spend[o["customer"]] += usd(o)
        customer_orders[o["customer"]] += 1

    # ---- Monthly aggregates keyed by (year, month) — paid only ----
    month_revenue: dict[tuple, float] = defaultdict(float)
    month_orders: dict[tuple, int] = defaultdict(int)
    month_qty: dict[tuple, int] = defaultdict(int)
    for o in paid:
        dt = kolkata_month(o)
        key = (dt.year, dt.month)
        month_revenue[key] += usd(o)
        month_orders[key] += 1
        month_qty[key] += o["qty"]

    # ---- Monthly + Region keyed by (year, month, region) ----
    month_region_revenue: dict[tuple, float] = defaultdict(float)
    month_region_orders: dict[tuple, int] = defaultdict(int)
    for o in paid:
        dt = kolkata_month(o)
        key = (dt.year, dt.month, o["region"].lower())
        month_region_revenue[key] += usd(o)
        month_region_orders[key] += 1

    # ---- Monthly + Product revenue ----
    month_product_revenue: dict[tuple, float] = defaultdict(float)
    month_product_qty: dict[tuple, int] = defaultdict(int)
    for o in paid:
        dt = kolkata_month(o)
        key = (dt.year, dt.month, o["product"])
        month_product_revenue[key] += usd(o)
        month_product_qty[key] += o["qty"]

    # ---- Region + Product ----
    region_product_revenue: dict[tuple, float] = defaultdict(float)
    region_product_qty: dict[tuple, int] = defaultdict(int)
    for o in paid:
        key = (o["region"].lower(), o["product"])
        region_product_revenue[key] += usd(o)
        region_product_qty[key] += o["qty"]

    # ---- Distinct customers per product (paid only) ----
    distinct_customers_by_product: dict[str, set] = defaultdict(set)
    for o in paid:
        distinct_customers_by_product[o["product"]].add(o["customer"])

    # ---- Sorted product list for NLP matching (longest first to avoid prefix errors) ----
    all_products = sorted(product_revenue.keys(), key=len, reverse=True)

    return {
        "total_revenue": total_revenue,
        "total_refunds": total_refunds,
        "product_revenue": dict(product_revenue),
        "product_qty": dict(product_qty),
        "region_revenue": dict(region_revenue),
        "region_qty": dict(region_qty),
        "region_orders": dict(region_orders),
        "customer_spend": dict(customer_spend),
        "customer_orders": dict(customer_orders),
        "month_revenue": dict(month_revenue),
        "month_orders": dict(month_orders),
        "month_qty": dict(month_qty),
        "month_region_revenue": dict(month_region_revenue),
        "month_region_orders": dict(month_region_orders),
        "month_product_revenue": dict(month_product_revenue),
        "month_product_qty": dict(month_product_qty),
        "region_product_revenue": dict(region_product_revenue),
        "region_product_qty": dict(region_product_qty),
        "distinct_customers_by_product": {k: v for k, v in distinct_customers_by_product.items()},
        "all_products": all_products,
        "paid_orders": paid,
        "refunded_orders": refunded,
    }


# ---------------------------------------------------------------------------
# NLP helpers
# ---------------------------------------------------------------------------
def extract_date_filter(question: str) -> tuple[int | None, int | None]:
    """
    Return (year, month) extracted from the question.
    Either value may be None if not mentioned.
    Examples:
      "in January 2026"  → (2026, 1)
      "in 2026"          → (2026, None)
      "in March"         → (None, 3)
    """
    q = question.lower()

    # Try "Month YYYY" or "YYYY Month"
    for name, num in MONTH_NAMES.items():
        # "January 2026" / "jan 2026"
        m = re.search(rf"\b{name}\b.*?\b(20\d\d)\b", q)
        if m:
            return int(m.group(1)), num
        m = re.search(rf"\b(20\d\d)\b.*?\b{name}\b", q)
        if m:
            return int(m.group(1)), num

    # Only month name
    for name, num in MONTH_NAMES.items():
        if re.search(rf"\b{name}\b", q):
            return None, num

    # Only year (4-digit 20xx)
    m = re.search(r"\b(20\d\d)\b", q)
    if m:
        return int(m.group(1)), None

    return None, None


def extract_region(question: str) -> str | None:
    """Return the region name (lowercase, original capitalisation preserved in KNOWN_REGIONS) or None."""
    q = question.lower()
    for region in KNOWN_REGIONS:
        if re.search(rf"\b{region}\b", q):
            return region
    return None


def extract_customer(question: str) -> str | None:
    """Return e.g. 'C1119' if mentioned in the question, else None."""
    m = re.search(r"\bC\d{3,}\b", question, re.IGNORECASE)
    return m.group(0).upper() if m else None


def extract_product(question: str, all_products: list[str]) -> str | None:
    """Return the first matching product name (longest-match wins)."""
    q = question.lower()
    for product in all_products:
        if product.lower() in q:
            return product
    return None


def fmt_usd(value: float) -> str:
    return f"${value:,.2f}"


# ---------------------------------------------------------------------------
# Lifespan — replaces deprecated @app.on_event("startup")
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(application: FastAPI):
    """Fetch and pre-compute data once at startup; held for the app lifetime."""
    orders, rates = load_ledger_data()
    agg = precompute(orders, rates)
    application.state.agg = agg
    application.state.rates = rates
    yield  # app runs here


app = FastAPI(title="The Ledger Agent", lifespan=lifespan)


def startup():
    """Convenience wrapper used by the test suite to populate app.state without
    going through the async lifespan context manager."""
    orders, rates = load_ledger_data()
    app.state.agg = precompute(orders, rates)
    app.state.rates = rates


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/")
def home():
    return {"message": "The Ledger Agent is running"}


# ---------------------------------------------------------------------------
# Main question-answering endpoint
# ---------------------------------------------------------------------------
@app.post("/answer")
def answer_question(request: QuestionRequest):
    question = request.question.strip()
    q = question.lower()
    agg = app.state.agg

    # ---- Extract filters ----
    year, month = extract_date_filter(q)
    region = extract_region(q)
    customer = extract_customer(question)
    product = extract_product(q, agg["all_products"])

    has_date = year is not None or month is not None
    has_region = region is not None

    # ---- Intent signals ----
    is_revenue = any(w in q for w in ["revenue", "sales", "earned", "earning", "income", "sale"])
    is_refund = any(w in q for w in ["refund", "refunded"])
    is_qty = any(w in q for w in ["how many", "units", "quantity", "qty", "sold", "pieces", "count of orders", "number of orders", "orders were", "orders in", "orders from", "orders placed"])
    is_highest = any(w in q for w in ["highest", "most", "top", "best", "maximum", "max"])
    is_order_count = any(w in q for w in ["how many orders", "number of orders", "count of orders", "orders were", "orders placed", "orders in", "orders from", "total orders"])
    is_customer_spend = customer is not None and any(w in q for w in ["spend", "spent", "paid", "revenue", "total", "how much", "amount"])
    is_product_count = product is not None and any(w in q for w in ["how many", "units", "quantity", "qty", "sold", "pieces"])

    # =========================================================================
    # ROUTING — most specific rules first
    # =========================================================================

    # 1. Customer spend
    if is_customer_spend:
        spend = agg["customer_spend"].get(customer, 0.0)
        return {"answer": fmt_usd(spend)}

    # 2. Refund total
    if is_refund:
        return {"answer": fmt_usd(agg["total_refunds"])}

    # 3. Highest-revenue product (optionally filtered by month/year or region)
    if is_highest and (is_revenue or "product" in q):
        if not product:
            # Compute best product from appropriate filtered set
            if has_date and has_region:
                scores = {}
                for prod in agg["all_products"]:
                    rev = 0.0
                    for key, val in agg["month_product_revenue"].items():
                        ky, km, kp = key
                        if kp != prod:
                            continue
                        if year and ky != year:
                            continue
                        if month and km != month:
                            continue
                        rev += val
                    # intersect with region: use region_product_revenue per month
                    # We need month+region+product; approximate via paid_orders
                    scores[prod] = rev
                # Rebuild properly from paid_orders
                scores = defaultdict(float)
                for o in agg["paid_orders"]:
                    dt = to_kolkata(parse_timestamp(o["created_at"]))
                    if year and dt.year != year:
                        continue
                    if month and dt.month != month:
                        continue
                    if o["region"].lower() != region:
                        continue
                    scores[o["product"]] += o["amount"] * app.state.rates[o["currency"]]
            elif has_date:
                scores = defaultdict(float)
                for o in agg["paid_orders"]:
                    dt = to_kolkata(parse_timestamp(o["created_at"]))
                    if year and dt.year != year:
                        continue
                    if month and dt.month != month:
                        continue
                    scores[o["product"]] += o["amount"] * app.state.rates[o["currency"]]
            elif has_region:
                scores = {
                    p: agg["region_product_revenue"].get((region, p), 0.0)
                    for p in agg["all_products"]
                }
            else:
                scores = agg["product_revenue"]

            if scores:
                best = max(scores, key=scores.get)
                return {"answer": f"{best}: {fmt_usd(scores[best])}"}
            return {"answer": "No paid sales found."}

    is_distinct_customers = "distinct" in q and "customer" in q

    # 4a. Distinct customers who bought a product
    if is_distinct_customers and product:
        count = len(agg["distinct_customers_by_product"].get(product, set()))
        return {"answer": str(count)}

    # 4. Product qty sold (with optional date/region filter)
    if is_product_count and product:
        if has_date or has_region:
            total = 0
            for o in agg["paid_orders"]:
                if o["product"] != product:
                    continue
                if has_region and o["region"].lower() != region:
                    continue
                if has_date:
                    dt = to_kolkata(parse_timestamp(o["created_at"]))
                    if year and dt.year != year:
                        continue
                    if month and dt.month != month:
                        continue
                total += o["qty"]
            return {"answer": str(total)}
        return {"answer": str(agg["product_qty"].get(product, 0))}

    # 5. Product revenue (with optional date/region filter)
    if product and (is_revenue or not is_qty):
        if has_date and has_region:
            total = sum(
                o["amount"] * app.state.rates[o["currency"]]
                for o in agg["paid_orders"]
                if o["product"] == product
                and o["region"].lower() == region
                and (not year or to_kolkata(parse_timestamp(o["created_at"])).year == year)
                and (not month or to_kolkata(parse_timestamp(o["created_at"])).month == month)
            )
            return {"answer": fmt_usd(total)}
        elif has_date:
            total = 0.0
            for key, val in agg["month_product_revenue"].items():
                ky, km, kp = key
                if kp != product:
                    continue
                if year and ky != year:
                    continue
                if month and km != month:
                    continue
                total += val
            return {"answer": fmt_usd(total)}
        elif has_region:
            total = agg["region_product_revenue"].get((region, product), 0.0)
            return {"answer": fmt_usd(total)}
        else:
            return {"answer": fmt_usd(agg["product_revenue"].get(product, 0.0))}

    # 6. Order count (with optional date/region filter)
    if is_order_count:
        if has_date and has_region:
            total = sum(
                1 for o in agg["paid_orders"]
                if o["region"].lower() == region
                and (not year or to_kolkata(parse_timestamp(o["created_at"])).year == year)
                and (not month or to_kolkata(parse_timestamp(o["created_at"])).month == month)
            )
            return {"answer": str(total)}
        elif has_date:
            total = 0
            for key, val in agg["month_orders"].items():
                ky, km = key
                if year and ky != year:
                    continue
                if month and km != month:
                    continue
                total += val
            return {"answer": str(total)}
        elif has_region:
            return {"answer": str(agg["region_orders"].get(region, 0))}
        else:
            return {"answer": str(len(agg["paid_orders"]))}

    # 7. Revenue (with optional date/region filter)
    if is_revenue:
        if has_date and has_region:
            total = 0.0
            for key, val in agg["month_region_revenue"].items():
                ky, km, kr = key
                if kr != region:
                    continue
                if year and ky != year:
                    continue
                if month and km != month:
                    continue
                total += val
            return {"answer": fmt_usd(total)}
        elif has_date:
            total = 0.0
            for key, val in agg["month_revenue"].items():
                ky, km = key
                if year and ky != year:
                    continue
                if month and km != month:
                    continue
                total += val
            return {"answer": fmt_usd(total)}
        elif has_region:
            return {"answer": fmt_usd(agg["region_revenue"].get(region, 0.0))}
        else:
            return {"answer": fmt_usd(agg["total_revenue"])}

    # 8. Fallback
    return {"answer": "I don't know how to answer that question yet."}
