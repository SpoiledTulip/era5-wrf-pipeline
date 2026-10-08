#!/usr/bin/env python3
"""Validate the mechanical consistency of a WRF case YAML."""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys

try:
    import yaml
except ImportError:
    yaml = None

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case_yaml")
    args = ap.parse_args()
    if yaml is None:
        print("PyYAML is required to validate case.yaml", file=sys.stderr)
        return 2
    data = yaml.safe_load(Path(args.case_yaml).read_text(encoding="utf-8"))
    errors = []
    domains = data.get("domain", {}).get("domains", [])
    if not domains:
        errors.append("domain.domains is empty")
    for idx, dom in enumerate(domains):
        ratio = int(dom.get("parent_grid_ratio", 1))
        for axis in ("e_we", "e_sn"):
            n = int(dom.get(axis, 0))
            if n < 2 or (n - 1) % ratio != 0:
                errors.append(f"d{idx+1} {axis}: (value-1) must be divisible by ratio {ratio}")
        if idx:
            parent = domains[int(dom.get("parent_id", 1)) - 1]
            for axis, start_key in (("e_we", "i_parent_start"), ("e_sn", "j_parent_start")):
                start = int(dom.get(start_key, 1))
                size = int(dom.get(axis, 0))
                psize = int(parent.get(axis, 0))
                span = (size - 1) // ratio
                if start < 6 or start + span > psize - 5:
                    errors.append(f"d{idx+1} {start_key}/{axis}: child outside 5-grid safety margin")
    v = data.get("vertical", {})
    if int(v.get("e_vert", 0)) < 2 or int(v.get("num_metgrid_levels", 0)) < 2:
        errors.append("vertical e_vert and num_metgrid_levels must be positive")
    if int(v.get("p_top_requested", 0)) <= 0:
        errors.append("vertical.p_top_requested must be positive Pa")
    interval = int(data.get("driver", {}).get("interval_seconds", 0))
    if interval <= 0 or interval % 3600:
        errors.append("driver.interval_seconds must be a positive whole number of hours")
    try:
        start = datetime.strptime(data["start_utc"], "%Y-%m-%d_%H:%M:%S")
        end = start + timedelta(hours=int(data["duration_hours"]))
        print(f"window: {start} -> {end} UTC; interval={interval}s")
    except Exception as exc:
        errors.append(f"invalid start_utc/duration_hours: {exc}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK: {data.get('name', 'case')} passed mechanical checks ({len(domains)} domain(s))")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
