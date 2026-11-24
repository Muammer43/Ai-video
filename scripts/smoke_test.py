#!/usr/bin/env python3
"""Çalışan bir kurulumu uçtan uca sınar (yalnızca standart kütüphane). Kullanım: python scripts/smoke_test.py http://host:8000"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
tok = None


def call(method, path, body=None, headers=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    if tok:
        h["Authorization"] = "Bearer " + tok
    req = urllib.request.Request(BASE + path, method=method, headers=h, data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name, extra)
    if not cond:
        sys.exit(1)


s, h = call("GET", "/api/v1/health")
check("health", s == 200 and h["ok"])
email = f"smoke_{int(time.time())}@example.com"
s, r = call("POST", "/api/v1/auth/register", {"email": email, "password": "Passw0rd!smoke"})
check("register", s == 201)
tok = r["access_token"]
for _ in range(60):  # Celery worker açılışını bekle
    s, st = call("GET", "/api/v1/system/status")
    if st["workers"]["ok"]:
        break
    time.sleep(1)
check("system status: db/redis/worker", st["database"]["ok"] and st["redis"]["ok"] and st["workers"]["ok"], f"workers={st['workers'].get('online')}")
s, p = call("POST", "/api/v1/projects", {"topic": "Temiz kurulum duman testi", "category": "Bilim", "duration": 15, "quality_tier": "draft", "media_mode": "slideshow", "platforms": []},
            {"Idempotency-Key": "smoke-" + email})
check("create project", s == 202)
pid = p["project"]["id"]
t0 = time.time()
while time.time() - t0 < 300:
    s, d = call("GET", "/api/v1/projects/" + pid)
    if d["status"] in ("NEEDS_REVIEW", "APPROVED", "FAILED", "PUBLISHED"):
        break
    time.sleep(1)
check("pipeline finished (worker via Redis)", d["status"] == "NEEDS_REVIEW", f"{d['status']} skor={d.get('quality_score')} {d.get('error', '')}")
s, m = call("GET", f"/api/v1/projects/{pid}/media")
req = urllib.request.Request(BASE + m["video"]["path"])
data = urllib.request.urlopen(req, timeout=60).read()
check("video downloadable", len(data) > 10000 and data[4:8] == b"ftyp", f"{len(data)} bayt")
open("/tmp/aivf_smoke.mp4", "wb").write(data)
print("SMOKE TESTİ GEÇTİ")
