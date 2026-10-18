
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

url = os.getenv("LEDGER_API_URL")

if not url:
    raise RuntimeError("LEDGER_API_URL is missing from .env")

all_orders = []
page_count = 0

with httpx.Client(timeout=20, follow_redirects=True) as client:
    while url:
        response = client.get(url)
        response.raise_for_status()
        data = response.json()

        orders = data.get("orders", [])
        all_orders.extend(orders)
        page_count += 1

        print(
            f"Fetched page {data.get('page', '?')}/"
            f"{data.get('pages', '?')} — "
            f"{len(orders)} orders"
        )

        url = data.get("next")

print("\nFinished fetching!")
print("Pages fetched:", page_count)
print("Total order rows:", len(all_orders))

if all_orders:
    print("Fields:", list(all_orders[0].keys()))
    print("First order:", all_orders[0])
