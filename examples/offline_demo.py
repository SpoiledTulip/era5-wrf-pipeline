#!/usr/bin/env python3
"""Generate a synthetic field and offline figure; no WRF/CDS/SSH required."""
from pathlib import Path
import argparse
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "era5-wrf-pipeline" / "scripts"))
import wxplot
import matplotlib.pyplot as plt
import cartopy.crs as ccrs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "examples" / "output")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    lon, lat = np.meshgrid(np.linspace(120, 132, 49), np.linspace(20, 32, 49))
    field = 1012 - 30 * np.exp(-((lon - 126)**2 + (lat - 26)**2) / 10)
    u, v = -(lat - 26), lon - 126
    np.savez_compressed(args.out_dir / "synthetic_slp.npz",
                        lon=lon, lat=lat, field=field, u=u, v=v,
                        var="slp", unit="hPa", source="synthetic; not a model result")
    wxplot.setup("en")
    fig = plt.figure(figsize=(9, 7.5))
    ax = fig.add_subplot(111, projection=ccrs.PlateCarree())
    ax.set_extent([120, 132, 20, 32], crs=ccrs.PlateCarree())
    gl = ax.gridlines(draw_labels=True, linewidth=0.4, alpha=0.5)
    gl.top_labels = False
    gl.right_labels = False
    mappable = wxplot.plane(ax, lon, lat, field, levels=np.arange(982, 1014, 2), var="slp")
    wxplot.wind_barbs(ax, lon, lat, u, v, skip=6)
    ax.set_title("Synthetic sea level pressure and wind (demo)")
    wxplot.add_colorbar(fig, mappable, ax, "SLP (hPa)", orientation="horizontal")
    wxplot.footnote(ax, "Synthetic data only | Not ERA5 or WRF output | No boundary data")
    wxplot.save(fig, args.out_dir / "synthetic_slp.png")


if __name__ == "__main__":
    main()
