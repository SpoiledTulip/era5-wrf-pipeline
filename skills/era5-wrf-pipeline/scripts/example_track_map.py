#!/usr/bin/env python3
"""示例：用 wxplot.py 画路径对比图（本地运行，台风个例可选使用）。

输入是 extract_wrf.py track 导出的 CSV；可再叠加实况或 ERA5 路径做对比。
只有用户明确要求对比时才叠加，不要默认加。

用法：
  python example_track_map.py extract/track.csv track.png \
      --title "Typhoon track" --gis /path/to/gis_data
"""
from __future__ import annotations
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxplot  # noqa: E402


def read_track(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append((r["time"],
                         float(r["lat"]), float(r["lon"]),
                         float(r.get("slp_hPa") or "nan")))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="extract_wrf.py track 导出的 CSV")
    ap.add_argument("out")
    ap.add_argument("--title", default="Simulated track")
    ap.add_argument("--gis", default=None)
    ap.add_argument("--language", default="en", choices=["en", "zh"])
    ap.add_argument("--style", default="draft", choices=list(wxplot.STYLE))
    ap.add_argument("--obs-csv", default=None,
                    help="可选：实况/再分析路径 CSV，列名 time,lat,lon")
    ap.add_argument("--extent", default=None,
                    help="可选：西,东,南,北（不给则按路径自动留边）")
    ap.add_argument("--marker-every", type=int, default=8)
    ap.add_argument("--footnote", default="")
    args = ap.parse_args()

    sim = read_track(args.csv)
    if not sim:
        raise SystemExit("路径 CSV 为空")

    wxplot.setup(args.language)
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs

    if args.extent:
        extent = [float(v) for v in args.extent.split(",")]
    else:
        lats = [r[1] for r in sim]; lons = [r[2] for r in sim]
        pad = max(1.5, (max(lons) - min(lons)) * 0.15)
        pady = max(1.5, (max(lats) - min(lats)) * 0.15)
        extent = [min(lons) - pad, max(lons) + pad,
                  min(lats) - pady, max(lats) + pady]

    spec = wxplot.STYLE[args.style]
    fig = plt.figure(figsize=spec["figsize"])
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    wxplot.china_map(ax, extent, gis_root=args.gis, language=args.language)

    wxplot.track(ax, [r[2] for r in sim], [r[1] for r in sim],
                 color="#d62728", lw=2.2,
                 label="WRF simulated" if args.language == "en" else "WRF 模拟",
                 marker_every=args.marker_every)

    if args.obs_csv:
        obs = read_track(args.obs_csv)
        wxplot.track(ax, [r[2] for r in obs], [r[1] for r in obs],
                     color="#1a7a1a", lw=2.0,
                     label="Observed / reanalysis" if args.language == "en"
                           else "实况/再分析",
                     marker_every=args.marker_every)

    ax.set_title(args.title, fontsize=13, fontweight="bold", pad=10)
    ax.legend(loc="upper left", fontsize=10, framealpha=0.95)
    if args.footnote:
        wxplot.footnote(ax, args.footnote, style=args.style)
    wxplot.save(fig, args.out, style=args.style)
    print(f"track points: {len(sim)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
