
import os
import httpx
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from dotenv import load_dotenv

load_dotenv()

base_url = os.getenv("LEDGER_API_URL")

if not base_url:
    raise ValueError("LEDGER_API_URL was not found in .env")


def build_endpoint(path):
    parsed = urlparse(base_url)
    params = parse_qs(parsed.query)
    params["path"] = [path]

    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        urlencode(params, doseq=True),
        parsed.fragment
    ))


def parse_timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


with httpx.Client(timeout=30) as client:
    # Fetch all order records from the export endpoint.
    response = client.get(build_endpoint("/export"))
    response.raise_for_status()

    orders = [
        __import__("json").loads(line)
        for line in response.text.splitlines()
        if line.strip()
    ]

    # Fetch currency rates.
    response = client.get(build_endpoint("/rates"))
    response.raise_for_status()
    rates = response.json()["usd_per_unit"]


# Keep the latest updated version of each order ID.
latest_orders = {}

for order in orders:
    order_id = order["id"]

    if (
        order_id not in latest_orders
        or parse_timestamp(order["updated_at"])
        > parse_timestamp(latest_orders[order_id]["updated_at"])
    ):
        latest_orders[order_id] = order

unique_orders = list(latest_orders.values())

print("Total exported rows:", len(orders))
print("Unique order IDs:", len(unique_orders))
print("Duplicate rows removed:", len(orders) - len(unique_orders))

print("\nStatuses:")
for status in sorted({o["status"] for o in unique_orders}):
    print(f"  {status}: {sum(o['status'] == status for o in unique_orders)}")

print("\nRevenue from paid orders, in USD:")

revenue = sum(
    order["amount"] * rates[order["currency"]]
    for order in unique_orders
    if order["status"] == "paid"
)

print(f"${revenue:,.2f}")

print("\nRefunded orders, in USD:")

refunds = sum(
    order["amount"] * rates[order["currency"]]
    for order in unique_orders
    if order["status"] == "refunded"
)

print(f"${refunds:,.2f}")
