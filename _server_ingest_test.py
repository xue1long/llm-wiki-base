"""Ingest all novel raw docs via server API and report bugs."""
import time
import requests
from pathlib import Path

BASE = "http://127.0.0.1:18765"
PROJECT_ID = "8dd46257-e46d-4bf8-b8d8-ba60b2aea54d"
proj_root = Path("knowledge/novel-wiki")
raw_dir = proj_root / "raw" / "sources"

raw_files = sorted(raw_dir.glob("*.md"))
print(f"Found {len(raw_files)} raw documents\n")

results = []
for i, raw_path in enumerate(raw_files):
    label = f"[{i+1}/{len(raw_files)}]"
    rel = f"raw/sources/{raw_path.name}"
    print(f"{'='*60}")
    print(f"{label} POST ingest: {rel}")
    t0 = time.time()

    try:
        resp = requests.post(
            f"{BASE}/api/v1/projects/{PROJECT_ID}/ingest",
            json={"source": rel},
            timeout=10,
        )
        elapsed = time.time() - t0
        body = resp.json()
        status = body.get("status")
        task_id = body.get("taskId")

        if status == "ignored":
            print(f"  IGNORED ({elapsed:.1f}s): {body.get('reason')}")
            results.append((raw_path.name, "IGNORED", ""))
            continue

        print(f"  QUEUED: {task_id} ({elapsed:.1f}s)")

        # Poll for completion
        max_wait = 600
        poll_interval = 5
        waited = 0
        final_status = "unknown"
        while waited < max_wait:
            time.sleep(poll_interval)
            waited += poll_interval
            try:
                sr = requests.get(
                    f"{BASE}/api/v1/projects/{PROJECT_ID}/ingest/status/{task_id}",
                    timeout=5,
                )
                if sr.status_code == 200:
                    st = sr.json()
                    final_status = st.get("status", "unknown")
                    if final_status in ("succeeded", "failed"):
                        break
                elif sr.status_code == 404:
                    # Task not tracked yet, keep polling
                    pass
            except Exception:
                pass
            if waited % 30 == 0:
                print(f"  ... waiting ({waited}s, status={final_status})")

        elapsed = time.time() - t0
        if final_status == "succeeded":
            print(f"  OK ({elapsed:.1f}s)")
            results.append((raw_path.name, "OK", task_id))
        elif final_status == "failed":
            # Get error detail
            try:
                sr = requests.get(
                    f"{BASE}/api/v1/projects/{PROJECT_ID}/ingest/status/{task_id}"
                )
                err = sr.json().get("error", "unknown")
            except Exception:
                err = "unknown"
            print(f"  FAILED ({elapsed:.1f}s): {err}")
            results.append((raw_path.name, "FAILED", str(err)[:200]))
        else:
            print(f"  TIMEOUT ({elapsed:.1f}s): status={final_status}")
            results.append((raw_path.name, "TIMEOUT", final_status))

    except requests.exceptions.ConnectionError:
        elapsed = time.time() - t0
        print(f"  SERVER DOWN ({elapsed:.1f}s)")
        results.append((raw_path.name, "SERVER_DOWN", ""))
        break
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ERROR ({elapsed:.1f}s): {e}")
        results.append((raw_path.name, "ERROR", str(e)[:200]))

print("\n" + "=" * 60)
print("SUMMARY:")
for name, status, info in results:
    print(f"  {status:11s} | {name}")
ok = sum(1 for _, s, _ in results if s == "OK")
print(f"\n{ok}/{len(results)} succeeded")
