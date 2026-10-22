"""Build results/processing_metrics.csv from REAL CloudWatch logs of the deployed function.

    python tools/collect_metrics.py --region eu-west-1 --since-minutes 120
    python tools/collect_metrics.py --review results/label_review.csv   # label usefulness %

Needs boto3 + AWS credentials. Reports only what the logs contain - no invented numbers.
"""
import argparse
import csv
import json
import os
import time

ap = argparse.ArgumentParser()
ap.add_argument("--region", default="eu-west-1")
ap.add_argument("--function", default="smartthumb-sa-processor")
ap.add_argument("--since-minutes", type=int, default=120)
ap.add_argument("--review", help="reviewed label CSV (column 'useful' = yes/no) -> prints usefulness %%")
args = ap.parse_args()

if args.review:
    with open(args.review, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("useful", "").strip().lower() in ("yes", "no")]
    yes = sum(r["useful"].strip().lower() == "yes" for r in rows)
    print(f"Label usefulness: {yes}/{len(rows)} = {100*yes/max(len(rows),1):.1f}%  (target >= 80%)")
    raise SystemExit

import boto3  # noqa: E402

logs = boto3.client("logs", region_name=args.region)
group = f"/aws/lambda/{args.function}"
start = int((time.time() - args.since_minutes * 60) * 1000)
events, durations = [], []
for page in logs.get_paginator("filter_log_events").paginate(logGroupName=group, startTime=start):
    for e in page["events"]:
        msg = e["message"].strip()
        if msg.startswith("REPORT"):
            for part in msg.split("\t"):
                if part.startswith("Duration:"):
                    durations.append(float(part.split()[1]))
        i = msg.find("{")
        if i >= 0:
            try:
                d = json.loads(msg[i:])
                if "event" in d:
                    d["_ts"] = e["timestamp"]
                    events.append(d)
            except json.JSONDecodeError:
                pass

created = [e for e in events if e["event"] == "thumbnail_created"]
rejected = [e for e in events if e["event"] == "rejected"]
errors = [e for e in events if e["event"] == "error"]

os.makedirs("results", exist_ok=True)
with open("results/processing_metrics.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["timestamp_utc", "source_key", "original_bytes", "thumbnail_bytes", "reduction_pct", "original_dims", "thumbnail_dims", "processing_ms", "labels_status", "labels"])
    for e in created:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(e["_ts"] / 1000))
        w.writerow([ts, e["source_key"], e["original_bytes"], e["thumbnail_bytes"], e["reduction_pct"], e["original_dims"], e["thumbnail_dims"], e["processing_ms"], e["labels_status"], "|".join(e.get("labels", []))])

with open("results/label_review.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["source_key", "label", "useful"])  # reviewer fills 'yes' / 'no'
    for e in created:
        for lab in e.get("labels", []):
            w.writerow([e["source_key"], lab, ""])

n_valid = len(created) + len(errors)
print(f"thumbnails created : {len(created)}")
print(f"rejected (invalid) : {len(rejected)}")
print(f"errors             : {len(errors)}")
if n_valid:
    print(f"valid-image success: {100*len(created)/n_valid:.1f}%  (target >= 95%)")
if created:
    print(f"avg size reduction : {sum(e['reduction_pct'] for e in created)/len(created):.1f}%  (target >= 50%)")
if durations:
    print(f"Lambda duration    : avg {sum(durations)/len(durations):.0f} ms, max {max(durations):.0f} ms (REPORT lines, n={len(durations)})")
print("Wrote results/processing_metrics.csv and results/label_review.csv (fill 'useful', then run --review)")
