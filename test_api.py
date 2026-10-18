
import os
import httpx
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from dotenv import load_dotenv

load_dotenv()

url = os.getenv("LEDGER_API_URL")

if not url:
    print("ERROR: LEDGER_API_URL was not found in .env")
    raise SystemExit(1)

try:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    # Keep the existing authentication parameters,
    # but change only the endpoint path.
    for path in ["/rates", "/export"]:
        params["path"] = [path]
        endpoint = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(params, doseq=True),
            parsed.fragment
        ))

        print(f"\n--- Checking {path} ---")

        response = httpx.get(endpoint, timeout=15)
        print("HTTP status:", response.status_code)

        
        if response.is_success:
            print("Content-Type:", response.headers.get("content-type"))
            print("Response preview:")
            print(response.text[:2500])

            print("\nFirst few lines:")
            for i, line in enumerate(response.text.splitlines()[:5], start=1):
                print(f"Line {i}: {line[:500]}")
        else:
            print("Response:", response.text[:500])


except Exception as e:
    print("ERROR:", repr(e))
