#!/usr/bin/env python3
"""Extract lightweight WRF products on Kunshan; never copy wrfout itself.

在超算上（用 nc_env 的 python）运行，从 wrfout 提取轻量产品，供 scp 回本地出图。

四种模式（用子命令选）：
  plane    平面场降采样 → npz（最常用）
  series   点/区域平均时间序列 → csv
  profile  垂直剖面（过指定点）→ npz
  track    台风中心逐时次路径 → csv（可选，仅台风个例用）

示例：
  # 500 hPa 位势高度 + 风，第 0 时次
  python extract_wrf.py plane wrfout_d01_2026-08-05_00:00:00 \
      --var z --level 500 --time 0 --out extract/z500_t0.npz --with-wind
  # 累积降水（末时次）
  python extract_wrf.py plane wrfout_d01_2026-08-05_00:00:00 \
      --var rain --time -1 --out extract/rain_acc.npz
  # 湛江附近区域平均的 SLP 时间序列
  python extract_wrf.py series wrfout_d01_2026-08-05_00:00:00 \
      --var slp --lat 21.2 --lon 110.4 --radius 100 --out extract/slp_series.csv
  # 台风中心路径
  python extract_wrf.py track wrfout_d01_2026-08-05_00:00:00 --out extract/track.csv
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path
import numpy as np

# wrf.getvar 变量名 → (绘图用语, 单位)。
VAR_MAP = {
    "slp":   ("Sea level pressure", "hPa",      1.0),
    "z":     ("Geopotential height", "m",       1.0),
    "tk":    ("Temperature", "K",               1.0),
    "tc":    ("Temperature", "degC",            1.0),
    "rh":    ("Relative humidity", "%",         1.0),
    "avo":   ("Absolute vorticity", "1e-5 s-1", 1.0),
    "pvo":   ("Potential vorticity", "PVU",     1.0),
    "cape":  ("CAPE", "J kg-1",                 1.0),
    "pw":    ("Precipitable water", "mm",       1.0),
    "uvmet10": ("10 m wind speed", "m s-1",     1.0),
    "ua":    ("U wind", "m s-1",                1.0),
    "va":    ("V wind", "m s-1",                1.0),
    "rain":  ("Accumulated rainfall", "mm",     1.0),   # rainc+rainnc
    "t2":    ("2 m temperature", "degC",        1.0),
}


def _load(wrfout):
    try:
        from netCDF4 import Dataset
        from wrf import getvar
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(f"wrf-python/netCDF4 unavailable: {exc}")
    return Dataset(wrfout), getvar


# 三维（带气压层）变量；其余为二维诊断量
LEVEL_VARS = ("ua", "va", "z", "tk", "tc", "rh", "avo", "pvo")
D2_VARS = ("slp", "uvmet10", "t2", "rain", "pw", "cape")


def _field(ds, getvar, name, timeidx, level, need_level=True):
    """取变量。need_level=True 时三维变量必须给 --level；False 则返回整层原始场。"""
    if name == "rain":
        return (np.asarray(getvar(ds, "RAINC", timeidx=timeidx), dtype=float)
                + np.asarray(getvar(ds, "RAINNC", timeidx=timeidx), dtype=float))
    if name == "t2":
        return np.asarray(getvar(ds, "T2", timeidx=timeidx), dtype=float) - 273.15
    if name == "cape":
        return np.asarray(getvar(ds, "cape_2d", timeidx=timeidx), dtype=float)[0]
    if name == "uvmet10":
        uv = np.asarray(getvar(ds, "uvmet10", timeidx=timeidx), dtype=float)
        return np.hypot(uv[0], uv[1])
    if name in LEVEL_VARS:
        if need_level and level is None:
            raise SystemExit(f"--var {name} 需要 --level（如 500）")
        return np.asarray(getvar(ds, name, timeidx=timeidx), dtype=float)
    kw = {}
    if name == "slp":
        kw["units"] = "hPa"
    return np.asarray(getvar(ds, name, timeidx=timeidx, **kw), dtype=float)


def _at_level(arr, ds, getvar, level, timeidx):
    """Interpolate on pressure in hPa for the requested time, masking below-ground levels."""
    from wrf import interplevel
    p = np.asarray(getvar(ds, "pressure", timeidx=timeidx), dtype=float)
    result = interplevel(arr, p, float(level), meta=False)
    return np.asarray(np.ma.filled(result, np.nan), dtype=float)


def _slice_area(lat, lon, lat0, lon0, radius_km):
    """按中心+半径取子区域，降低导出体积。"""
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(np.cos(np.radians(lat0)), 1e-6))
    j = np.where((lat[:, 0] >= lat0 - dlat) & (lat[:, 0] <= lat0 + dlat))[0]
    i = np.where((lon[0, :] >= lon0 - dlon) & (lon[0, :] <= lon0 + dlon))[0]
    if j.size == 0 or i.size == 0:
        raise SystemExit("--radius 范围内没有格点，请检查 --lat/--lon")
    return slice(j[0], j[-1] + 1), slice(i[0], i[-1] + 1)


def cmd_plane(args):
    ds, getvar = _load(args.wrfout)
    try:
        lat = np.asarray(ds.variables["XLAT"][0])
        lon = np.asarray(ds.variables["XLONG"][0])
        nt = len(ds.dimensions["Time"])
        t = args.time if args.time >= 0 else nt + args.time
        field = _field(ds, getvar, args.var, t, args.level)
        if args.level is not None:
            if args.var not in LEVEL_VARS:
                raise SystemExit("--level is only valid for three-dimensional variables")
            field = _at_level(field, ds, getvar, args.level, t)
        out = {"lon": lon, "lat": lat, "field": field.astype(np.float32),
               "var": args.var, "unit": VAR_MAP[args.var][1],
               "time_utc": _stamp(ds, t), "time_index": np.array([t])}

        if args.with_wind:
            if args.level is not None:
                uv = np.asarray(getvar(ds, "uvmet", timeidx=t), dtype=float)
                u = _at_level(uv[0], ds, getvar, args.level, t)
                v = _at_level(uv[1], ds, getvar, args.level, t)
            else:
                uv = np.asarray(getvar(ds, "uvmet10", timeidx=t), dtype=float)
                u, v = uv[0], uv[1]
            out["u"] = u.astype(np.float32)
            out["v"] = v.astype(np.float32)

        if args.radius and args.lat is not None and args.lon is not None:
            sj, si = _slice_area(lat, lon, args.lat, args.lon, args.radius)
            for k in ("lon", "lat", "field", "u", "v"):
                if k in out:
                    out[k] = out[k][sj, si]

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out_path, **out)
        stamp = _stamp(ds, t)
        desc, unit, _ = VAR_MAP.get(args.var, (args.var, "?", 1.0))
        print(f"wrote {out_path} | {desc} [{unit}] | time={stamp} | shape={out['field'].shape}")
    finally:
        ds.close()
    return 0


def cmd_series(args):
    ds, getvar = _load(args.wrfout)
    try:
        lat = np.asarray(ds.variables["XLAT"][0])
        lon = np.asarray(ds.variables["XLONG"][0])
        sj, si = _slice_area(lat, lon, args.lat, args.lon, args.radius)
        nt = len(ds.dimensions["Time"])
        rows = []
        for t in range(nt):
            field = _field(ds, getvar, args.var, t, args.level)
            if args.level is not None:
                if args.var not in LEVEL_VARS:
                    raise SystemExit("--level is only valid for three-dimensional variables")
                field = _at_level(field, ds, getvar, args.level, t)
            val = float(np.nanmean(field[sj, si]))
            rows.append((_stamp(ds, t), round(val, 4)))
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time", args.var])
            w.writerows(rows)
        print(f"wrote {out_path} ({len(rows)} rows, center=({args.lat},{args.lon}) r={args.radius}km)")
    finally:
        ds.close()
    return 0


def cmd_profile(args):
    ds, getvar = _load(args.wrfout)
    try:
        if args.var in D2_VARS:
            raise SystemExit(
                f"--var {args.var} 是二维量，没有垂直剖面。"
                f"剖面请用三维变量：{'/'.join(LEVEL_VARS)}")
        lat = np.asarray(ds.variables["XLAT"][0])
        lon = np.asarray(ds.variables["XLONG"][0])
        j = int(np.argmin(np.abs(lat[:, 0] - args.lat)))
        i = int(np.argmin(np.abs(lon[0, :] - args.lon)))
        nt = len(ds.dimensions["Time"])
        t = args.time if args.time >= 0 else nt + args.time
        p = np.asarray(getvar(ds, "pressure", timeidx=t), dtype=float)
        field = _field(ds, getvar, args.var, t, None, need_level=False)
        z = np.asarray(getvar(ds, "z", timeidx=t), dtype=float)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            out_path,
            pressure=p[:, j, i].astype(np.float32),
            height_m=z[:, j, i].astype(np.float32),
            unit=VAR_MAP[args.var][1],
            pressure_unit="hPa",
            field=field[:, j, i].astype(np.float32),
            var=args.var,
            lat=lat[j, i], lon=lon[j, i],
        )
        print(f"wrote {out_path} | {args.var} profile at "
              f"({lat[j, i]:.2f},{lon[j, i]:.2f}) t={_stamp(ds, t)}")
    finally:
        ds.close()
    return 0


def cmd_track(args):
    ds, getvar = _load(args.wrfout)
    try:
        lat = np.asarray(ds.variables["XLAT"][0])
        lon = np.asarray(ds.variables["XLONG"][0])
        rows = []
        prev = None
        warned = []
        for t in range(len(ds.dimensions["Time"])):
            slp = np.asarray(getvar(ds, "slp", timeidx=t), dtype=float)
            slp[:3, :] = np.nan; slp[-3:, :] = np.nan
            slp[:, :3] = np.nan; slp[:, -3:] = np.nan
            if prev is None:
                j, i = np.unravel_index(np.nanargmin(slp), slp.shape)
            else:
                pj, pi = prev
                win = args.window
                j0, i0 = max(0, pj - win), max(0, pi - win)
                j1, i1 = min(slp.shape[0], pj + win + 1), min(slp.shape[1], pi + win + 1)
                sub = slp[j0:j1, i0:i1]
                dj, di = np.unravel_index(np.nanargmin(sub), sub.shape)
                j, i = j0 + dj, i0 + di
                # 跟丢检测：窗内最低点若贴着窗口边缘，说明真实中心可能在窗外，
                # 继续跟下去会给出看似正常、实际错误的路径。
                if _edge_hit(dj, di, sub.shape):
                    warned.append((_stamp(ds, t), "hit search window edge"))
                if (j, i) == prev:
                    warned.append((_stamp(ds, t), "center did not move"))
            prev = (j, i)
            rows.append((_stamp(ds, t), round(float(lat[j, i]), 3),
                         round(float(lon[j, i]), 3), round(float(slp[j, i]), 1)))
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time", "lat", "lon", "slp_hPa"])
            w.writerows(rows)
        print(f"wrote {out_path} ({len(rows)} rows, window={args.window})")
        if warned:
            print(f"⚠️ 疑似跟丢 {len(warned)} 次（路径可能不可信）：")
            for stamp, why in warned[:5]:
                print(f"   {stamp}  {why}")
            if len(warned) > 5:
                print(f"   ... 另有 {len(warned) - 5} 次")
            print("   建议：加大 --window，或先确认台风中心全程在域内。")
    finally:
        ds.close()
    return 0


def _stamp(ds, t):
    raw = ds.variables["Times"][t]
    return "".join(x.decode() if isinstance(x, bytes) else str(x) for x in raw)


def _edge_hit(dj, di, shape):
    """最低点是否落在搜索窗口边缘。

    落在边缘说明真实最低点可能在窗外，继续跟随会得到错误路径——
    这类错误不会抛异常，只会安静地给出一条看似合理的假路径。
    """
    return dj in (0, shape[0] - 1) or di in (0, shape[1] - 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("plane", help="平面场降采样 → npz")
    p.add_argument("wrfout")
    p.add_argument("--var", default="slp", choices=sorted(VAR_MAP))
    p.add_argument("--level", type=float, default=None, help="气压层 hPa（z/ua/va 等需要）")
    p.add_argument("--time", type=int, default=0, help="时次索引，-1=最后")
    p.add_argument("--with-wind", action="store_true", help="同时导出风场")
    p.add_argument("--lat", type=float, default=None)
    p.add_argument("--lon", type=float, default=None)
    p.add_argument("--radius", type=float, default=None, help="子区域半径 km")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_plane)

    s = sub.add_parser("series", help="区域平均时间序列 → csv")
    s.add_argument("wrfout")
    s.add_argument("--var", default="slp", choices=sorted(VAR_MAP))
    s.add_argument("--level", type=float, default=None)
    s.add_argument("--lat", type=float, required=True)
    s.add_argument("--lon", type=float, required=True)
    s.add_argument("--radius", type=float, default=50.0)
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_series)

    r = sub.add_parser("profile", help="垂直剖面 → npz")
    r.add_argument("wrfout")
    r.add_argument("--var", default="tk", choices=sorted(LEVEL_VARS),
                   help="只支持三维变量（有垂直层）")
    r.add_argument("--lat", type=float, required=True)
    r.add_argument("--lon", type=float, required=True)
    r.add_argument("--time", type=int, default=0)
    r.add_argument("--out", required=True)
    r.set_defaults(func=cmd_profile)

    k = sub.add_parser("track", help="台风中心路径 → csv（可选）")
    k.add_argument("wrfout")
    k.add_argument("--window", type=int, default=30, help="连续性搜索窗口（格点）")
    k.add_argument("--out", required=True)
    k.set_defaults(func=cmd_track)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
