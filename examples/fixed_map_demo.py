#!/usr/bin/env python3
"""用仓库中修复后的 wxplot.py 出图，验证国界与底图配色。"""
import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "era5-wrf-pipeline" / "scripts"))
import wxplot  # noqa: E402
import cartopy.crs as ccrs  # noqa: E402
import numpy as np  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gis", required=True, help="Natural Earth 矢量根目录")
    ap.add_argument("--out", default="maps/fixed_demo.png")
    args = ap.parse_args()

    wxplot.setup("zh")
    lon, lat = np.meshgrid(np.linspace(105, 125, 140), np.linspace(20, 42, 140))
    field = 1012 - 26 * np.exp(-((lon - 117) ** 2 + (lat - 28) ** 2) / 9)
    u, v = -(lat - 28) * 0.8, (lon - 117) * 0.8

    fig = plt.figure(figsize=(9, 7.5))
    ax = fig.add_subplot(111, projection=ccrs.PlateCarree())
    wxplot.china_map(ax, [105, 125, 20, 42], gis_root=args.gis,
                     language="zh", strict=True)
    m = ax.contourf(lon, lat, field, levels=np.arange(986, 1014, 2),
                    cmap="RdBu_r", transform=ccrs.PlateCarree(),
                    extend="both", zorder=2)
    cs = ax.contour(lon, lat, field, levels=np.arange(986, 1014, 4), colors="k",
                    linewidths=0.7, transform=ccrs.PlateCarree(), zorder=4)
    ax.clabel(cs, fmt="%d", fontsize=8)
    ax.barbs(lon[::12, ::12], lat[::12, ::12], u[::12, ::12], v[::12, ::12],
             length=4.2, linewidth=0.4, transform=ccrs.PlateCarree(), zorder=5)
    wxplot.add_colorbar(fig, m, ax, "SLP (hPa)", orientation="horizontal")
    ax.set_title("修复后底图：SLP + 10 m 风（v0.2.1）",
                 fontsize=13, fontweight="bold", pad=10)
    wxplot.footnote(ax, "合成演示数据 | 非 ERA5/WRF 结果 | 边界：Natural Earth 仅供示意")
    wxplot.save(fig, args.out, style="draft")


if __name__ == "__main__":
    main()
