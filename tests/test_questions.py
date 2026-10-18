"""
Automated tests for the Ledger Agent question-answering endpoint.

Uses httpx.AsyncClient with ASGITransport (in-process, no HTTP server).
The app's startup event fetches real data once per session; subsequent tests
are pure dict lookups — fast and safe under concurrency.

Expected values were computed directly from the real dataset (see implementation_plan.md).
Monetary comparisons allow ±$0.02 tolerance for floating-point accumulation.
"""

import asyncio
import time
import pytest
import httpx
from httpx import AsyncClient, ASGITransport
from starlette.testclient import TestClient

# Import app — dotenv is called at module level in main.py
from main import app, startup


# ---------------------------------------------------------------------------
# Session-scoped fixtures: startup runs once, client reused for all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def trigger_startup():
    """Run the sync startup function once for the whole test session."""
    startup()


@pytest.fixture(scope="session")
def sync_client():
    """Synchronous ASGI test client (no lifespan re-trigger)."""
    # lifespan="off" because we called startup() above manually
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def ask(client: TestClient, question: str) -> str:
    resp = client.post("/", json={"question": question})
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "answer" in data, f"No 'answer' key in response: {data}"
    return data["answer"]


def parse_usd(s: str) -> float:
    """'$1,085,171.72' → 1085171.72"""
    return float(s.replace("$", "").replace(",", ""))


def approx_usd(actual: str, expected: float, tol: float = 0.02) -> bool:
    return abs(parse_usd(actual) - expected) <= tol


# ---------------------------------------------------------------------------
# Revenue tests
# ---------------------------------------------------------------------------

def test_total_revenue(sync_client):
    answer = ask(sync_client, "What is the total revenue?")
    assert approx_usd(answer, 1_085_171.72), f"Got: {answer}"


def test_total_revenue_alternate_wording(sync_client):
    answer = ask(sync_client, "How much did we earn in total sales?")
    assert approx_usd(answer, 1_085_171.72), f"Got: {answer}"


def test_total_revenue_income(sync_client):
    answer = ask(sync_client, "What is the total income from paid orders?")
    assert approx_usd(answer, 1_085_171.72), f"Got: {answer}"


# ---------------------------------------------------------------------------
# Refund tests
# ---------------------------------------------------------------------------

def test_total_refunds(sync_client):
    answer = ask(sync_client, "What is the total value of refunds?")
    assert approx_usd(answer, 152_543.05), f"Got: {answer}"


def test_refund_alternate_wording(sync_client):
    answer = ask(sync_client, "How much was refunded?")
    assert approx_usd(answer, 152_543.05), f"Got: {answer}"


# ---------------------------------------------------------------------------
# Product revenue tests
# ---------------------------------------------------------------------------

def test_product_revenue_air_fryer(sync_client):
    answer = ask(sync_client, "What is the revenue from Air Fryer?")
    assert approx_usd(answer, 158_898.80), f"Got: {answer}"


def test_product_revenue_rice_cooker(sync_client):
    answer = ask(sync_client, "How much revenue did Rice Cooker generate?")
    assert approx_usd(answer, 217_385.68), f"Got: {answer}"


def test_product_revenue_blender(sync_client):
    answer = ask(sync_client, "Total sales for Blender?")
    assert approx_usd(answer, 75_570.26), f"Got: {answer}"


def test_product_revenue_toaster(sync_client):
    answer = ask(sync_client, "What is the Toaster revenue?")
    assert approx_usd(answer, 180_384.48), f"Got: {answer}"


def test_product_revenue_grinder(sync_client):
    answer = ask(sync_client, "Revenue from Grinder sales?")
    assert approx_usd(answer, 81_465.65), f"Got: {answer}"


def test_product_revenue_kettle(sync_client):
    answer = ask(sync_client, "How much did Kettle earn?")
    assert approx_usd(answer, 138_185.24), f"Got: {answer}"


def test_product_revenue_juicer(sync_client):
    answer = ask(sync_client, "What is the Juicer revenue?")
    assert approx_usd(answer, 114_021.53), f"Got: {answer}"


def test_product_revenue_mixer(sync_client):
    answer = ask(sync_client, "What are the total sales for Mixer?")
    assert approx_usd(answer, 119_260.08), f"Got: {answer}"


# ---------------------------------------------------------------------------
# Product quantity tests
# ---------------------------------------------------------------------------

def test_product_qty_mixer(sync_client):
    answer = ask(sync_client, "How many Mixer units were sold?")
    assert answer == "1137", f"Got: {answer}"


def test_product_qty_juicer(sync_client):
    answer = ask(sync_client, "How many Juicer were sold?")
    assert answer == "1243", f"Got: {answer}"


def test_product_qty_kettle(sync_client):
    answer = ask(sync_client, "What is the quantity sold for Kettle?")
    assert answer == "1236", f"Got: {answer}"


def test_product_qty_toaster(sync_client):
    answer = ask(sync_client, "How many Toaster units were sold?")
    assert answer == "1298", f"Got: {answer}"


def test_product_qty_blender(sync_client):
    answer = ask(sync_client, "How many Blender were sold?")
    assert answer == "1229", f"Got: {answer}"


# ---------------------------------------------------------------------------
# Highest-revenue product
# ---------------------------------------------------------------------------

def test_highest_revenue_product(sync_client):
    answer = ask(sync_client, "Which product has the highest revenue?")
    assert answer.startswith("Rice Cooker"), f"Got: {answer}"


def test_best_selling_product(sync_client):
    answer = ask(sync_client, "What is the top earning product?")
    assert answer.startswith("Rice Cooker"), f"Got: {answer}"


def test_most_revenue_product(sync_client):
    answer = ask(sync_client, "Which product generated the most revenue?")
    assert answer.startswith("Rice Cooker"), f"Got: {answer}"


# ---------------------------------------------------------------------------
# Region revenue tests
# ---------------------------------------------------------------------------

def test_revenue_north(sync_client):
    answer = ask(sync_client, "What is the revenue from the North region?")
    assert approx_usd(answer, 223_899.61), f"Got: {answer}"


def test_revenue_south(sync_client):
    answer = ask(sync_client, "How much revenue came from South?")
    assert approx_usd(answer, 221_721.97), f"Got: {answer}"


def test_revenue_central(sync_client):
    answer = ask(sync_client, "What are the sales in the Central region?")
    assert approx_usd(answer, 213_197.27), f"Got: {answer}"


def test_revenue_east(sync_client):
    answer = ask(sync_client, "Revenue from East region?")
    assert approx_usd(answer, 207_729.11), f"Got: {answer}"


def test_revenue_west(sync_client):
    answer = ask(sync_client, "How much was earned in the West region?")
    assert approx_usd(answer, 218_623.75), f"Got: {answer}"


# ---------------------------------------------------------------------------
# Date-filtered revenue
# ---------------------------------------------------------------------------

def test_revenue_january_2026(sync_client):
    answer = ask(sync_client, "What is the revenue in January 2026?")
    assert approx_usd(answer, 180_148.10), f"Got: {answer}"


def test_revenue_february_2026(sync_client):
    answer = ask(sync_client, "What is the total revenue in February 2026?")
    assert approx_usd(answer, 176_103.01), f"Got: {answer}"


def test_revenue_march_2026(sync_client):
    answer = ask(sync_client, "Revenue for March 2026?")
    assert approx_usd(answer, 177_092.68), f"Got: {answer}"


def test_revenue_may_2026(sync_client):
    answer = ask(sync_client, "How much revenue was earned in May 2026?")
    assert approx_usd(answer, 193_332.62), f"Got: {answer}"


# ---------------------------------------------------------------------------
# Customer spend
# ---------------------------------------------------------------------------

def test_customer_spend_c1192(sync_client):
    answer = ask(sync_client, "How much did customer C1192 spend?")
    assert approx_usd(answer, 8_787.74), f"Got: {answer}"


def test_customer_spend_c1213(sync_client):
    answer = ask(sync_client, "What is the total amount paid by C1213?")
    assert approx_usd(answer, 8_497.98), f"Got: {answer}"


def test_customer_spend_c1091(sync_client):
    answer = ask(sync_client, "How much has C1091 spent in total?")
    assert approx_usd(answer, 8_079.66), f"Got: {answer}"


# ---------------------------------------------------------------------------
# Order count
# ---------------------------------------------------------------------------

def test_total_order_count(sync_client):
    answer = ask(sync_client, "How many orders were placed in total?")
    assert answer == "3217", f"Got: {answer}"


def test_order_count_north(sync_client):
    """Order count for North region — check it's in a plausible range."""
    answer = ask(sync_client, "How many orders in the North region?")
    count = int(answer)
    assert 500 < count < 900, f"Implausible order count for North: {answer}"


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

def test_unknown_question(sync_client):
    answer = ask(sync_client, "What is the meaning of life?")
    # Should return the fallback string, not crash
    assert isinstance(answer, str) and len(answer) > 0


# ---------------------------------------------------------------------------
# Concurrency — 10 simultaneous requests via threads
# ---------------------------------------------------------------------------

def test_concurrent_requests(sync_client):
    """
    10 identical questions fired concurrently via threads.
    All must return the correct answer; total wall time < 5 s.
    """
    question = "What is the total revenue?"
    expected = 1_085_171.72
    results = []
    errors = []

    def worker():
        try:
            results.append(ask(sync_client, question))
        except Exception as e:
            errors.append(str(e))

    import threading
    threads = [threading.Thread(target=worker) for _ in range(10)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - start

    assert not errors, f"Errors during concurrent requests: {errors}"
    for ans in results:
        assert approx_usd(ans, expected), f"Wrong answer under concurrency: {ans}"
    assert elapsed < 5.0, f"Concurrent requests took too long: {elapsed:.2f}s"
