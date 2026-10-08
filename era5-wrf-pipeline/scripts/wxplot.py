#!/usr/bin/env python3
"""Shared local plotting conventions for lightweight WRF fields.

本地公共绘图模块。所有出图脚本都应调用这里的函数，以保证底图、字体、
配色、落款和 language/style 参数全局一致。

用法示例见同目录 example_plane_field.py / example_track_map.py。
"""
from __future__ import annotations
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.io.shapereader as shpreader

# ---------------------------------------------------------------- 规格档位
STYLE = {
    "draft":        {"dpi": 150, "scale": 1.00, "figsize": (9.0, 7.5)},
    "presentation": {"dpi": 200, "scale": 1.15, "figsize": (11.0, 9.0)},
    "publication":  {"dpi": 300, "scale": 1.25, "figsize": (7.5, 6.0)},
}

# ---------------------------------------------------------------- 地名表
# 按 language 切换；坐标为标注锚点（经度, 纬度）。
# 注意：台湾、香港、澳门均为中国省级行政区，标注统一按省级处理。
PROVINCE_LABELS = {
    "en": {
        "北京": "Beijing", "天津": "Tianjin", "上海": "Shanghai", "重庆": "Chongqing",
        "河北": "Hebei", "山西": "Shanxi", "辽宁": "Liaoning", "吉林": "Jilin",
        "黑龙江": "Heilongjiang", "江苏": "Jiangsu", "浙江": "Zhejiang", "安徽": "Anhui",
        "福建": "Fujian", "江西": "Jiangxi", "山东": "Shandong", "河南": "Henan",
        "湖北": "Hubei", "湖南": "Hunan", "广东": "Guangdong", "广西": "Guangxi",
        "海南": "Hainan", "四川": "Sichuan", "贵州": "Guizhou", "云南": "Yunnan",
        "陕西": "Shaanxi", "甘肃": "Gansu", "青海": "Qinghai", "内蒙古": "Inner Mongolia",
        "宁夏": "Ningxia", "新疆": "Xinjiang", "西藏": "Tibet", "台湾": "Taiwan",
        "香港": "Hong Kong", "澳门": "Macao",
    },
    "zh": {
        "北京": "北京", "天津": "天津", "上海": "上海", "重庆": "重庆",
        "河北": "河北", "山西": "山西", "辽宁": "辽宁", "吉林": "吉林",
        "黑龙江": "黑龙江", "江苏": "江苏", "浙江": "浙江", "安徽": "安徽",
        "福建": "福建", "江西": "江西", "山东": "山东", "河南": "河南",
        "湖北": "湖北", "湖南": "湖南", "广东": "广东", "广西": "广西",
        "海南": "海南", "四川": "四川", "贵州": "贵州", "云南": "云南",
        "陕西": "陕西", "甘肃": "甘肃", "青海": "青海", "内蒙古": "内蒙古",
        "宁夏": "宁夏", "新疆": "新疆", "西藏": "西藏", "台湾": "台湾",
        "香港": "香港", "澳门": "澳门",
    },
}

# 标注锚点（经度, 纬度）
PROVINCE_XY = {
    "北京": (116.4, 40.2), "天津": (117.4, 39.3), "上海": (121.5, 31.2),
    "重庆": (107.6, 29.9), "河北": (115.2, 38.9), "山西": (112.3, 37.6),
    "辽宁": (122.8, 41.6), "吉林": (126.3, 43.7), "黑龙江": (128.0, 47.4),
    "江苏": (119.5, 33.0), "浙江": (120.2, 29.2), "安徽": (117.2, 31.8),
    "福建": (118.2, 26.2), "江西": (115.7, 27.5), "山东": (118.2, 36.4),
    "河南": (113.5, 33.9), "湖北": (112.3, 31.0), "湖南": (111.8, 27.6),
    "广东": (113.5, 23.4), "广西": (108.6, 23.6), "海南": (109.8, 19.2),
    "四川": (102.7, 30.6), "贵州": (106.7, 26.8), "云南": (101.5, 25.0),
    "陕西": (108.9, 35.2), "甘肃": (103.8, 36.5), "青海": (96.0, 35.6),
    "内蒙古": (111.7, 43.5), "宁夏": (106.2, 37.3), "新疆": (85.0, 41.5),
    "西藏": (88.0, 31.5), "台湾": (121.0, 23.7), "香港": (114.2, 22.3),
    "澳门": (113.5, 22.2),
}

# 常用色标（按要素），供各脚本统一取用
CMAPS = {
    "slp": "RdBu_r", "height": "RdBu_r", "temp": "RdBu_r",
    "rain": "Blues", "vorticity": "RdBu_r", "humidity": "YlGnBu",
    "wind": "viridis", "default": "RdBu_r",
}


# ---------------------------------------------------------------- 字体
def setup(language="en"):
    """注册字体：en 用 Arial/DejaVu Sans，zh 用 YaHei/SimHei 依次回退。"""
    if language == "zh":
        for name in ("Microsoft YaHei", "SimHei", "WenQuanYi Zen Hei"):
            try:
                fm.findfont(fm.FontProperties(family=name), fallback_to_default=False)
                plt.rcParams["font.sans-serif"] = [name]
                break
            except Exception:
                continue
        else:
            print("[wxplot] 警告：未找到中文字体，中文可能显示为方块")
    else:
        plt.rcParams["font.sans-serif"] = ["Arial", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


# ---------------------------------------------------------------- 底图
def china_map(ax, extent, gis_root=None, language="en",
              label_provinces=None, coast=True, ocean=True, ne_scale="10m"):
    """画中国区域底图。

    extent: [west, east, south, north]
    gis_root: Natural Earth 矢量根目录（含 ne_10m_admin0 / ne_10m_admin1）
    label_provinces: 要标注的省名列表（中文键）；None=自动按范围判定
    ne_scale: 底图要素分辨率，默认 "10m"（与省界/国界同级，且通常已缓存）

    ⚠️ 不要用默认的 110m：cfeature.LAND/OCEAN/LAKES 默认取 110m，
    若本地未缓存会触发联网下载，离线或受限环境下会直接失败。
    这里统一固定到 ne_scale，缺数据时给出明确提示而不是默默联网。
    """
    ax.set_extent(extent, crs=ccrs.PlateCarree())

    def _feat(name, **kw):
        f = cfeature.NaturalEarthFeature("physical", name, ne_scale,
                                         facecolor="none")
        f = f.with_scale(ne_scale)
        for k, v in kw.items():
            setattr(f, k, v)
        return f

    try:
        if ocean:
            ax.add_feature(_feat("ocean", facecolor="#d6e8f0"), zorder=0)
        ax.add_feature(_feat("land", facecolor="#f5f0e6"), zorder=0)
        ax.add_feature(_feat("lakes", facecolor="#cfe3ec"), zorder=1)
        if coast:
            ax.add_feature(_feat("coastline", edgecolor="#333333", linewidth=0.7),
                           zorder=2)
    except Exception as exc:
        print(f"[wxplot] 底图要素 {ne_scale} 不可用（{exc}）。"
              f"请先在有网环境运行一次以缓存 Natural Earth 数据，"
              f"或改用 ne_scale='50m'。")

    if gis_root:
        root = os.fspath(gis_root)
        for rel, color, width in (
            ("ne_10m_admin0/ne_10m_admin_0_boundary_lines_land.shp", "#444444", 1.0),
            ("ne_10m_admin1/ne_10m_admin_1_states_provinces_lines.shp", "#888888", 0.5),
        ):
            path = os.path.join(root, rel)
            if not os.path.exists(path):
                print(f"[wxplot] 缺矢量：{path}")
                continue
            for rec in shpreader.Reader(path).records():
                if rec.attributes.get("ADM0_NAME") == "China":
                    ax.add_geometries([rec.geometry], ccrs.PlateCarree(),
                                      facecolor="none", edgecolor=color,
                                      linewidth=width, zorder=3)

    names = PROVINCE_LABELS.get(language, PROVINCE_LABELS["en"])
    if label_provinces is None:
        # 落在范围里的省自动标注（留 15% 边距避免边缘挤字）
        dx = (extent[1] - extent[0]) * 0.02
        dy = (extent[3] - extent[2]) * 0.02
        label_provinces = [
            p for p, (x, y) in PROVINCE_XY.items()
            if extent[0] + dx <= x <= extent[1] - dx
            and extent[2] + dy <= y <= extent[3] - dy
        ]
    for p in label_provinces:
        if p not in PROVINCE_XY:
            continue
        x, y = PROVINCE_XY[p]
        ax.text(x, y, names.get(p, p), ha="center", va="center",
                fontsize=10, color="#666666",
                transform=ccrs.PlateCarree(), zorder=5,
                path_effects=[pe.withStroke(linewidth=2.8, foreground="white")])

    gl = ax.gridlines(draw_labels=True, linewidth=0.35, color="#999999", alpha=0.45)
    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {"size": 9}
    gl.ylabel_style = {"size": 9}
    return ax


# ---------------------------------------------------------------- 绘图原语
def plane(ax, lon, lat, field, *, levels=None, cmap=None, var=None,
          staggered=False, scale=1.0):
    """画平面标量场（等值填色）。返回 mappable 供 add_colorbar 使用。

    lon/lat 允许是 2D（wrfout 的 XLONG/XLAT）或 1D。
    field 允许是 masked array；NaN 会自动透明。
    var: CMAPS 里的键名，用于选默认色标。
    staggered: True 表示场在角点（比 lon/lat 大 1），画前会自动取平均。
    """
    import numpy as np
    lon = np.asarray(lon); lat = np.asarray(lat); field = np.asarray(field)
    if staggered:
        field = 0.25 * (field[:-1, :-1] + field[1:, 1:] + field[:-1, 1:] + field[1:, :-1])
        if lon.ndim == 2:
            lon = lon[:-1, :-1]; lat = lat[:-1, :-1]
    if levels is None:
        finite = field[np.isfinite(field)] if np.isfinite(field).any() else None
        if finite is None or finite.size == 0:
            levels = 21
        else:
            levels = np.linspace(float(finite.min()), float(finite.max()), 21)
    mappable = ax.contourf(lon, lat, field, levels=levels,
                           cmap=cmap or CMAPS.get(var or "default", "RdBu_r"),
                           transform=ccrs.PlateCarree(), extend="both", zorder=2)
    return mappable


def contour(ax, lon, lat, field, *, levels, color="k", lw=0.8,
            label=True, fmt="%d"):
    """画等值线并标注数值（如 SLP、位势高度）。"""
    cs = ax.contour(lon, lat, field, levels=levels, colors=color,
                    linewidths=lw, transform=ccrs.PlateCarree(), zorder=4)
    if label:
        ax.clabel(cs, fmt=fmt, fontsize=8)
    return cs


def wind_barbs(ax, lon, lat, u, v, *, skip=8, length=4.5, lw=0.5, scale=1.0):
    """画风羽。skip=抽稀间隔（避免过密），scale=风速缩放系数。"""
    import numpy as np
    lon = np.asarray(lon); lat = np.asarray(lat)
    u = np.asarray(u); v = np.asarray(v)
    if lon.ndim == 2:
        sl = (slice(None, None, skip), slice(None, None, skip))
        lon, lat, u, v = lon[sl], lat[sl], u[sl], v[sl]
    else:
        sl = slice(None, None, skip)
        lon, lat, u, v = lon[sl], lat[sl], u[sl], v[sl]
    ax.barbs(lon, lat, u * scale, v * scale, length=length, linewidth=lw,
             transform=ccrs.PlateCarree(), zorder=5)
    return ax


def quiver(ax, lon, lat, u, v, *, skip=10, scale=None, color="k"):
    """画箭头风场（比风羽更清爽，适合大范围示意）。"""
    import numpy as np
    lon = np.asarray(lon); lat = np.asarray(lat)
    u = np.asarray(u); v = np.asarray(v)
    if lon.ndim == 2:
        sl = (slice(None, None, skip), slice(None, None, skip))
        lon, lat, u, v = lon[sl], lat[sl], u[sl], v[sl]
    else:
        sl = slice(None, None, skip)
        lon, lat, u, v = lon[sl], lat[sl], u[sl], v[sl]
    if scale is None:
        spd = np.sqrt(u ** 2 + v ** 2)
        scale = float(np.nanpercentile(spd, 95)) or 1.0
    ax.quiver(lon, lat, u, v, scale=scale * 12, color=color,
              transform=ccrs.PlateCarree(), zorder=5)
    return ax


def track(ax, lon, lat, *, color="#d62728", label=None, lw=2.0,
          marker_every=None, marker="o"):
    """画路径线（台风路径、剖面线等）。marker_every=每 N 点加一个标记。"""
    import numpy as np
    lon = list(lon); lat = list(lat)
    ax.plot(lon, lat, "-", color=color, lw=lw,
            transform=ccrs.PlateCarree(), zorder=6, label=label)
    if marker_every:
        ax.plot(lon[::marker_every], lat[::marker_every], marker, color=color,
                ms=5, mec="white", mew=0.6, transform=ccrs.PlateCarree(), zorder=6)
    return ax


def add_colorbar(fig, mappable, ax, label, *, style="draft",
                 orientation="vertical", **kw):
    """加色标。label 请用国际符号（如 "SLP (hPa)"）。"""
    scale = STYLE.get(style, STYLE["draft"])["scale"]
    cbar = fig.colorbar(mappable, ax=ax, orientation=orientation,
                        pad=0.04, shrink=0.85, aspect=28, **kw)
    cbar.set_label(label, fontsize=10 * scale)
    cbar.ax.tick_params(labelsize=8 * scale)
    return cbar


def footnote(ax, text, style="draft"):
    """右下角落款：数据来源 / 模式版本 / 起报时间 / 边界性质说明。"""
    scale = STYLE.get(style, STYLE["draft"])["scale"]
    ax.text(0.995, 0.008, text, transform=ax.transAxes,
            fontsize=6 * scale, ha="right", va="bottom",
            style="italic", color="#666666", zorder=10)


def save(fig, path, style="draft"):
    """按档位保存。publication 额外输出同名 PDF（矢量）。"""
    if style not in STYLE:
        raise ValueError(f"unknown style: {style} (choose from {list(STYLE)})")
    path = os.fspath(path)
    spec = STYLE[style]
    fig.savefig(path, dpi=spec["dpi"], facecolor="white", bbox_inches="tight")
    if style == "publication":
        root, _ = os.path.splitext(path)
        fig.savefig(root + ".pdf", facecolor="white", bbox_inches="tight")
    plt.close(fig)
    print(f"[wxplot] saved {path} ({style}, {spec['dpi']} dpi)")
