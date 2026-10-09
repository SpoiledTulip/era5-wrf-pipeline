#!/usr/bin/env python3
"""Check case structure before WPS; optionally check observed met_em levels."""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys

import yaml

def validate(data, metgrid_levels=None):
    if not isinstance(data, dict):
        return ["case must be a YAML mapping"], []
    errors, warnings = [], []
    try:
        domains = data["domain"]["domains"]
        if not isinstance(domains, list) or not domains:
            raise ValueError("domain.domains must be a nonempty list")
        for idx, dom in enumerate(domains):
            ratio = int(dom["parent_grid_ratio"])
            if ratio < 1 or (idx == 0 and ratio != 1):
                errors.append(f"d{idx+1}: invalid parent_grid_ratio")
                continue
            for axis in ("e_we", "e_sn"):
                n = int(dom[axis])
                if n < 2 or (n - 1) % ratio:
                    errors.append(f"d{idx+1} {axis}: (value-1) must be divisible by {ratio}")
            if idx:
                parent_id = int(dom["parent_id"])
                if not 1 <= parent_id <= idx:
                    errors.append(f"d{idx+1}: parent_id must reference an earlier domain")
                    continue
                parent = domains[parent_id - 1]
                for axis, start_key in (("e_we", "i_parent_start"), ("e_sn", "j_parent_start")):
                    start = int(dom[start_key])
                    span = (int(dom[axis]) - 1) // ratio
                    if start < 6 or start + span > int(parent[axis]) - 5:
                        errors.append(f"d{idx+1} {start_key}/{axis}: outside 5-grid safety margin")
        vertical = data["vertical"]
        if int(vertical["e_vert"]) < 2:
            errors.append("vertical.e_vert must be >= 2")
        top = float(vertical["p_top_requested"])
        levels = [float(p) for p in data["driver"]["pressure_levels"]]
        if not levels or any(p <= 0 for p in levels):
            errors.append("driver.pressure_levels must contain positive hPa values")
        elif top < min(levels) * 100:
            errors.append("p_top_requested is above the highest requested pressure level")
        if top <= 0:
            errors.append("p_top_requested must be positive Pa")
        configured = vertical.get("num_metgrid_levels")
        if configured is not None and int(configured) < 2:
            errors.append("num_metgrid_levels must be >= 2 when set")
        if metgrid_levels is None:
            warnings.append("met_em levels not verified; do not submit real until checked")
        elif metgrid_levels < 2:
            errors.append("observed metgrid levels must be >= 2")
        elif configured is None:
            errors.append("set num_metgrid_levels from observed met_em before submitting real")
        elif int(configured) != metgrid_levels:
            errors.append("num_metgrid_levels does not match observed met_em")
        interval = int(data["driver"]["interval_seconds"])
        duration = int(data["duration_hours"])
        start = datetime.strptime(data["start_utc"], "%Y-%m-%d_%H:%M:%S")
        if interval <= 0 or interval % 3600:
            errors.append("driver.interval_seconds must be positive whole hours")
        elif duration <= 0 or duration * 3600 % interval:
            errors.append("duration must be positive and align with driver interval")
        if data.get("end_utc") and datetime.strptime(
            data["end_utc"], "%Y-%m-%d_%H:%M:%S"
        ) != start + timedelta(hours=duration):
            errors.append("end_utc does not match start_utc + duration_hours")
        step = data.get("time_step")
        if step is None:
            warnings.append("time_step is unset; choose and check before submitting WRF")
        elif float(step) <= 0:
            errors.append("time_step must be positive seconds")
        elif float(step) > 6 * min(float(domains[0]["dx"]), float(domains[0]["dy"])) / 1000:
            warnings.append("time_step exceeds 6 s per km heuristic; review stability")

        # ERA5 的 SST 在陆地上以 0 K 填充，细网格会在海岸线附近产生接近
        # 绝对零度的 2m 气温。网格 <= 15 km 时必须显式声明处理方式。
        # 见 references/era5-input-pitfalls.md
        source = str(data["driver"].get("source", "")).upper()
        finest_dx = min(float(dom["dx"]) for dom in domains)
        handling = data["driver"].get("sst_handling")
        valid_handling = {"vtable-remove", "fill-missing", "land-mask"}
        if source == "ERA5" and finest_dx <= 15000:
            if handling is None:
                warnings.append(
                    f"ERA5 with dx={finest_dx:.0f} m (<=15 km) may hit the SST "
                    "0 K fill-value trap: set driver.sst_handling to one of "
                    "vtable-remove / fill-missing / land-mask before submitting")
            elif str(handling) not in valid_handling:
                errors.append(
                    f"driver.sst_handling must be one of {sorted(valid_handling)}")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        errors.append(f"invalid or missing configuration field: {exc}")
    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_yaml")
    parser.add_argument("--metgrid-levels", type=int, help="actual num_metgrid_levels from met_em")
    args = parser.parse_args()
    try:
        data = yaml.safe_load(Path(args.case_yaml).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"ERROR: cannot read case YAML: {exc}", file=sys.stderr)
        return 1
    errors, warnings = validate(data, args.metgrid_levels)
    for message in warnings:
        print(f"WARNING: {message}")
    for message in errors:
        print(f"ERROR: {message}")
    if errors:
        return 1
    print("OK: pre-WPS mechanical checks passed; not scientific or data-coverage approval")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
