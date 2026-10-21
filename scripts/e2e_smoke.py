"""End-to-end smoke test for the appointment booking API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"


def req(method: str, path: str, body=None, token=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw
        return e.code, payload


def main() -> None:
    errors: list[str] = []

    def check(name: str, cond: bool, detail="") -> None:
        if cond:
            print(f"PASS  {name}")
        else:
            print(f"FAIL  {name} :: {detail}")
            errors.append(name)

    code, health = req("GET", "/health")
    check("health", code == 200 and health.get("status") == "ok" and health.get("redis") is True, health)

    code, alice = req(
        "POST",
        "/auth/login",
        {"email": "alice@clinic.example.com", "password": "PatientPass123!"},
    )
    check("login alice", code == 200 and "access_token" in (alice or {}), alice)
    alice_tok = (alice or {}).get("access_token")

    code, bob = req(
        "POST",
        "/auth/login",
        {"email": "bob@clinic.example.com", "password": "PatientPass123!"},
    )
    check("login bob", code == 200, bob)
    bob_tok = (bob or {}).get("access_token")

    code, doc = req(
        "POST",
        "/auth/login",
        {"email": "sarah@clinic.example.com", "password": "DoctorPass123!"},
    )
    check("login doctor", code == 200, doc)
    doc_tok = (doc or {}).get("access_token")

    code, bad = req(
        "POST",
        "/auth/login",
        {"email": "alice@clinic.example.com", "password": "wrong"},
    )
    check("bad login 401", code == 401, bad)

    code, doctors = req("GET", "/doctors")
    check("list doctors", code == 200 and isinstance(doctors, list) and len(doctors) >= 2, doctors)
    doctor_id = doctors[0]["id"] if doctors else 1

    code, slots = req("GET", f"/doctors/{doctor_id}/slots")
    check("list slots", code == 200 and isinstance(slots, list) and len(slots) > 0, slots)
    slot_id = slots[0]["id"]
    slot_id2 = slots[1]["id"] if len(slots) > 1 else None

    code, appt = req("POST", "/appointments/book", {"slot_id": slot_id}, token=alice_tok)
    check("book slot", code == 201 and appt and appt.get("status") == "pending", appt)
    appt_id = (appt or {}).get("id")

    code, dup = req("POST", "/appointments/book", {"slot_id": slot_id}, token=bob_tok)
    check("double book 409", code == 409, dup)

    if slot_id2:
        code, docbook = req("POST", "/appointments/book", {"slot_id": slot_id2}, token=doc_tok)
        check("doctor book forbidden", code == 403, docbook)

    code, mine = req("GET", "/appointments/my", token=alice_tok)
    check("my appointments patient", code == 200 and any(a["id"] == appt_id for a in mine), mine)

    code, schedule = req("GET", "/appointments/my", token=doc_tok)
    check("my appointments doctor", code == 200 and any(a["id"] == appt_id for a in schedule), schedule)

    code, conf = req("PATCH", f"/appointments/{appt_id}/status", {"status": "confirmed"}, token=doc_tok)
    check("confirm status", code == 200 and conf.get("status") == "confirmed", conf)

    code, steal = req("PATCH", f"/appointments/{appt_id}/cancel", token=bob_tok)
    check("cancel others forbidden", code == 403, steal)

    code, cancelled = req("PATCH", f"/appointments/{appt_id}/cancel", token=alice_tok)
    check("cancel own", code == 200 and cancelled.get("status") == "cancelled", cancelled)

    code, slots2 = req("GET", f"/doctors/{doctor_id}/slots")
    free_ids = {s["id"] for s in slots2}
    check("slot freed after cancel", slot_id in free_ids, free_ids)

    code, rebook = req("POST", "/appointments/book", {"slot_id": slot_id}, token=bob_tok)
    check("rebook freed slot", code == 201, rebook)

    code, noauth = req("GET", "/appointments/my")
    check("missing auth 401", code == 401, noauth)

    code, badslot = req("POST", "/appointments/book", {"slot_id": 999999}, token=alice_tok)
    check("invalid slot 404", code == 404, badslot)

    print("\n==== SUMMARY ====")
    print(f"Failures: {len(errors)}")
    if errors:
        print("Failed:", ", ".join(errors))
        raise SystemExit(1)
    print("All checks passed")


if __name__ == "__main__":
    main()
