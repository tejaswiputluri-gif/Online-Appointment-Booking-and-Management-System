"""
Concurrency smoke test — fires N parallel booking requests at the SAME slot.

Expect exactly one HTTP 201 and the rest HTTP 409.

Usage:
  1. Start the API and seed data
  2. Login as alice, note a free slot_id from GET /doctors/1/slots
  3. python -m scripts.concurrency_test --token <JWT> --slot-id <ID>

This is the demo you'd walk through in an SDE interview to prove the Redis lock works.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import urllib.error
import urllib.request


def attempt_book(base_url: str, token: str, slot_id: int) -> tuple[int, str]:
    req = urllib.request.Request(
        f"{base_url}/appointments/book",
        data=json.dumps({"slot_id": slot_id}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main() -> None:
    parser = argparse.ArgumentParser(description="Concurrent booking race test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", required=True, help="Patient JWT access token")
    parser.add_argument("--slot-id", type=int, required=True)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()

    print(f"Firing {args.workers} concurrent bookings at slot {args.slot_id} ...")
    results: list[tuple[int, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [
            pool.submit(attempt_book, args.base_url, args.token, args.slot_id)
            for _ in range(args.workers)
        ]
        for f in concurrent.futures.as_completed(futs):
            results.append(f.result())

    successes = [r for r in results if r[0] == 201]
    conflicts = [r for r in results if r[0] == 409]
    other = [r for r in results if r[0] not in (201, 409)]

    print(f"  201 Created : {len(successes)}")
    print(f"  409 Conflict: {len(conflicts)}")
    print(f"  Other       : {len(other)}")
    if other:
        print("  Unexpected responses:", other)

    if len(successes) == 1 and len(conflicts) == args.workers - 1:
        print("PASS — exactly one winner, no double-booking.")
    else:
        print("FAIL — expected exactly one 201 and the rest 409.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
