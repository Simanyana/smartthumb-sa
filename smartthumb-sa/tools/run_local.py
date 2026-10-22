"""Offline run: apply the exact Lambda image logic to tests/test_images/ and write a metrics CSV.

Use as (a) a safety net if the network/AWS fails during the demo and (b) a baseline.
These are LOCAL results (no S3/Lambda/CloudWatch) - label them as such in reports.
    python tools/run_local.py [input_dir] [output_dir]
"""
import csv
import os
import sys
import time

os.environ.setdefault("DEST_BUCKET", "local")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import types

try:
    import botocore.exceptions  # noqa: F401
except ImportError:  # local-only convenience; Lambda always has botocore
    bc = types.ModuleType("botocore"); ex = types.ModuleType("botocore.exceptions")
    ex.ClientError = type("ClientError", (Exception,), {}); bc.exceptions = ex
    sys.modules.update({"botocore": bc, "botocore.exceptions": ex})

import lambda_function as lf  # noqa: E402

root = os.path.join(os.path.dirname(__file__), "..")
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "tests", "test_images")
dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(root, "results", "local_thumbnails")
os.makedirs(dst, exist_ok=True)

rows, ok, rejected = [], 0, 0
for name in sorted(os.listdir(src)):
    path = os.path.join(src, name)
    size = os.path.getsize(path)
    ext = os.path.splitext(name)[1].lower()
    t0 = time.time()
    status, reason, tb, od, td = "", "", 0, "", ""
    if ext not in lf.ALLOWED_EXTENSIONS:
        status, reason = "rejected", "unsupported_extension"
    elif size == 0:
        status, reason = "rejected", "empty_file"
    else:
        try:
            with open(path, "rb") as f:
                thumb, fmt, o, t = lf.make_thumbnail(f.read())
            with open(os.path.join(dst, os.path.basename(lf.thumbnail_key(name, fmt))), "wb") as f:
                f.write(thumb)
            status, tb, od, td = "processed", len(thumb), f"{o[0]}x{o[1]}", f"{t[0]}x{t[1]}"
        except lf.InvalidImageError as exc:
            status, reason = "rejected", str(exc)
    ms = round((time.time() - t0) * 1000, 1)
    red = round((1 - tb / size) * 100, 1) if status == "processed" and size else ""
    rows.append([name, status, reason, size, tb or "", red, od, td, ms])
    ok += status == "processed"; rejected += status == "rejected"

out_csv = os.path.join(root, "results", "local_baseline_metrics.csv")
with open(out_csv, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["file", "status", "reject_reason", "original_bytes", "thumbnail_bytes", "reduction_pct", "original_dims", "thumbnail_dims", "local_ms"])
    w.writerows(rows)

reds = [r[5] for r in rows if r[5] != ""]
print(f"processed={ok} rejected={rejected} avg_reduction={sum(reds)/len(reds):.1f}% (n={len(reds)})")
print(f"valid-image success rate = {ok}/{ok} of valid files; invalid files rejected cleanly = {rejected}")
print("wrote", os.path.abspath(out_csv))
