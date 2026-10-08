#!/usr/bin/env python3
"""示例：用 wxplot.py 画平面场（本地运行）。

输入是 extract_wrf.py plane 导出的 npz。复制本文件改成你要的图即可，
新图型请沿用同样的调用方式，不要另起一套底图/字体设置。

用法：
  python example_plane_field.py extract/z500_t0.npz 500hPa_height.png \
      --title "Geopotential height at 500 hPa" --var height --unit gpm \
      --gis /path/to/gis_data --language en --style draft
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxplot  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("npz", help="extract_wrf.py plane 导出的 npz")
    ap.add_argument("out", help="输出图片路径")
    ap.add_argument("--title", default="")
    ap.add_argument("--var", default="default", help="取色标的键：slp/height/temp/rain/vorticity/...")
    ap.add_argument("--unit", default="")
    ap.add_argument("--gis", default=None, help="Natural Earth 矢量根目录")
    ap.add_argument("--language", default="en", choices=["en", "zh"])
    ap.add_argument("--style", default="draft", choices=list(wxplot.STYLE))
    ap.add_argument("--levels", type=int, default=21)
    ap.add_argument("--contour-every", type=float, default=None,
                    help="同时叠加等值线，间距按数值给（如 40 表示每 40 gpm 一条）")
    ap.add_argument("--footnote", default="")
    args = ap.parse_args()

    d = np.load(args.npz, allow_pickle=False)
    lon, lat, field = d["lon"], d["lat"], d["field"]
    has_wind = "u" in d.files and "v" in d.files

    wxplot.setup(args.language)
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs

    spec = wxplot.STYLE[args.style]
    fig = plt.figure(figsize=spec["figsize"])
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())

    pad_x = (float(lon.max()) - float(lon.min())) * 0.02
    pad_y = (float(lat.max()) - float(lat.min())) * 0.02
    extent = [float(lon.min()) - pad_x, float(lon.max()) + pad_x,
              float(lat.min()) - pad_y, float(lat.max()) + pad_y]
    wxplot.china_map(ax, extent, gis_root=args.gis, language=args.language)

    finite = field[np.isfinite(field)]
    if finite.size:
        levels = np.linspace(float(finite.min()), float(finite.max()), args.levels)
    else:
        levels = args.levels
    mappable = wxplot.plane(ax, lon, lat, field, levels=levels, var=args.var)

    if args.contour_every:
        step = args.contour_every
        lo = np.floor(float(finite.min()) / step) * step
        hi = np.ceil(float(finite.max()) / step) * step
        wxplot.contour(ax, lon, lat, field,
                       levels=np.arange(lo, hi + step, step))

    if has_wind:
        wxplot.wind_barbs(ax, lon, lat, d["u"], d["v"], skip=max(1, lon.shape[-1] // 20))

    unit = f" ({args.unit})" if args.unit else ""
    label = f"{args.var}{unit}" if args.title == "" else args.title
    if args.title:
        ax.set_title(args.title, fontsize=13, fontweight="bold", pad=10)
    wxplot.add_colorbar(fig, mappable, ax, label, style=args.style,
                        orientation="horizontal")
    if args.footnote:
        wxplot.footnote(ax, args.footnote, style=args.style)

    wxplot.save(fig, args.out, style=args.style)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
