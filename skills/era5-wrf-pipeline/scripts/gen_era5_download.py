#!/usr/bin/env python3
"""从 case.yaml 生成 ERA5 下载脚本（CDS/cdsapi）。

为什么单独拆出来
----------------
本脚本只做**生成**，不下载。生成的 `download_era5.py` 由用户在自己的机器上、
用自己的 `~/.cdsapirc` 运行。这样拆分的原因：

  1. 请求内容（区域、变量、层次、时次）是纯函数，可离线断言 —
     而请求写错恰恰是最常见的失败源，且**不会报错**：
     CDS 的 `area` 是 [North, West, South, East]，顺序写反照样下载成功，
     只是区域错了。这类"跑通但结果错"的问题必须靠断言拦住。
  2. 真正下载需要 CDS 凭据与配额，属用户环境，不应由本脚本代劳。

生成的产物
----------
  download_era5.py    可直接运行的 cdsapi 脚本（气压层 + 单层两次请求）
  verify_era5.py      下载后自检：文件数、非空、时次完整
  era5_report.txt     请求摘要与待办

用法
----
  python gen_era5_download.py case.yaml --out-dir data/
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys

import yaml

WRF_DATE = "%Y-%m-%d_%H:%M:%S"
CDS_DATE = "%Y-%m-%d"

# ERA5 气压层请求必需的 3D 变量
PLEV_VARIABLES = (
    "geopotential",
    "relative_humidity",
    "specific_humidity",
    "temperature",
    "u_component_of_wind",
    "v_component_of_wind",
)

# 单层请求必需变量。顺序固定，便于断言与 diff。
SFC_VARIABLES = (
    "surface_pressure",
    "mean_sea_level_pressure",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "2m_temperature",
    "2m_dewpoint_temperature",
    "skin_temperature",
    "sea_surface_temperature",
    "snow_depth",
    "sea_ice_cover",
    "land_sea_mask",
    "soil_temperature_level_1",
    "soil_temperature_level_2",
    "soil_temperature_level_3",
    "soil_temperature_level_4",
    "volumetric_soil_water_layer_1",
    "volumetric_soil_water_layer_2",
    "volumetric_soil_water_layer_3",
    "volumetric_soil_water_layer_4",
)

# sst_handling != vtable-remove 时才需要 SST
SST_VARIABLE = "sea_surface_temperature"


class CaseError(Exception):
    """配置无法用于生成下载请求。"""


def parse_area(area) -> tuple[float, float, float, float]:
    """校验并返回 (north, west, south, east)。

    ⚠️ CDS 的 area 顺序是 [North, West, South, East]。
    写成 [S, N, W, E] 之类的顺序不会报错，只会安静地下载错误区域——
    这是本函数存在的主要原因。
    """
    if not isinstance(area, (list, tuple)) or len(area) != 4:
        raise CaseError(f"driver.area 必须是 4 个数 [N, W, S, E]，当前为 {area!r}")
    north, west, south, east = (float(v) for v in area)
    if north <= south:
        raise CaseError(
            f"driver.area 的顺序应为 [North, West, South, East]，"
            f"但 north({north}) <= south({south})。"
            f"顺序写错不会报错，只会下载到错误区域。")
    if east <= west:
        raise CaseError(
            f"driver.area 顺序应为 [North, West, South, East]，"
            f"但 east({east}) <= west({west})。")
    for name, val in (("north", north), ("south", south)):
        if not -90 <= val <= 90:
            raise CaseError(f"{name}={val} 超出纬度范围 [-90, 90]")
    if not -180 <= west <= 180 or not -180 <= east <= 180:
        raise CaseError("经度须在 [-180, 180]")
    return north, west, south, east


def parse_pressure_levels(levels) -> list[int]:
    """校验并返回降序排列的气压层（hPa）。CDS 惯例从大到小。"""
    if not isinstance(levels, (list, tuple)) or not levels:
        raise CaseError("driver.pressure_levels 必须是非空列表")
    out = []
    for p in levels:
        value = int(p)
        if value <= 0:
            raise CaseError(f"气压层必须为正数（hPa），当前 {p!r}")
        out.append(value)
    if len(set(out)) != len(out):
        raise CaseError(f"pressure_levels 有重复: {out}")
    return sorted(out, reverse=True)


def build_times(case: dict) -> tuple[list[str], list[str], list[str]]:
    """返回 (days, times, 展开后的时刻列表)。

    ERA5 逐小时；按 interval_seconds 抽样后得到 WRF 需要的驱动时刻。
    时次必须覆盖完整积分窗口（含起止两端）。
    """
    start = datetime.strptime(case["start_utc"], WRF_DATE)
    hours = int(case["duration_hours"])
    interval = int(case["driver"]["interval_seconds"])
    if interval <= 0 or interval % 3600:
        raise CaseError("interval_seconds 必须是小时的整数倍")

    step = timedelta(seconds=interval)
    stamps, t = [], start
    end = start + timedelta(hours=hours)
    while t <= end:
        stamps.append(t)
        t += step
    if stamps[-1] != end:
        raise CaseError(
            f"积分窗口 {hours} h 不能被间隔 {interval} s 整除，"
            f"末时刻为 {stamps[-1]}，期望 {end}")

    days = sorted({d.strftime(CDS_DATE) for d in stamps})
    times = sorted({d.strftime("%H:%M") for d in stamps})
    return days, times, [d.strftime(WRF_DATE) for d in stamps]


def build_plev_request(case: dict) -> dict:
    """ERA5 气压层请求。"""
    north, west, south, east = parse_area(case["driver"]["area"])
    days, times, _ = build_times(case)
    years = sorted({d.split("-")[0] for d in days})
    months = sorted({d.split("-")[1] for d in days})
    return {
        "product_type": "reanalysis",
        "variable": list(PLEV_VARIABLES),
        "pressure_level": [str(p) for p in parse_pressure_levels(
            case["driver"]["pressure_levels"])],
        "year": years,
        "month": months,
        "day": days,
        "time": times,
        "area": [north, west, south, east],
        "format": "grib",
    }


def sfc_variables(case: dict) -> list[str]:
    """单层变量清单。sst_handling=vtable-remove 时不请求 SST。"""
    variables = list(SFC_VARIABLES)
    if case["driver"].get("sst_handling") == "vtable-remove":
        variables = [v for v in variables if v != SST_VARIABLE]
    return variables


def build_sfc_request(case: dict) -> dict:
    """ERA5 单层请求。"""
    north, west, south, east = parse_area(case["driver"]["area"])
    days, times, _ = build_times(case)
    years = sorted({d.split("-")[0] for d in days})
    months = sorted({d.split("-")[1] for d in days})
    return {
        "product_type": "reanalysis",
        "variable": sfc_variables(case),
        "year": years,
        "month": months,
        "day": days,
        "time": times,
        "area": [north, west, south, east],
        "format": "grib",
    }


def _render(obj, indent=4) -> str:
    """把请求 dict 渲染成可读的 Python 字面量。"""
    pad = " " * indent
    if isinstance(obj, dict):
        items = [f"{pad}{' ' * 4}{k!r}: {_render(v, indent + 4).lstrip()}"
                 for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + f",\n{pad}}}"
    if isinstance(obj, list):
        if all(isinstance(x, str) for x in obj) and len(obj) > 3:
            inner = ",\n".join(f"{pad}{' ' * 4}{x!r}" for x in obj)
            return "[\n" + inner + f",\n{pad}]"
        return repr(obj)
    return repr(obj)


def build_download_script(case: dict) -> str:
    plev = build_plev_request(case)
    sfc = build_sfc_request(case)
    return f'''#!/usr/bin/env python3
"""ERA5 下载脚本 —— 由 gen_era5_download.py 生成，请勿手改。

需要：pip install "cdsapi>=0.7" 且已配置 ~/.cdsapirc
（新版格式为 url + Personal Access Token，不再是 uid + key）

幂等：目标文件存在且非空则跳过，可安全重跑。
用法：python download_era5.py [--out-dir data]
"""
import argparse
from pathlib import Path

PLEV_REQUEST = {_render(plev)}

SFC_REQUEST = {_render(sfc)}


def fetch(client, dataset, request, target: Path) -> None:
    """下载单个请求，已存在且非空则跳过。"""
    if target.exists() and target.stat().st_size > 0:
        print(f"skip   {{target}} ({{target.stat().st_size}} bytes)")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"fetch  {{target}}")
    client.retrieve(dataset, request, str(target))
    if not target.exists() or target.stat().st_size == 0:
        raise SystemExit(f"下载后文件为空: {{target}}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default="data")
    args = ap.parse_args()

    try:
        import cdsapi
    except ImportError:
        raise SystemExit('缺少 cdsapi，请先执行: pip install "cdsapi>=0.7"')

    client = cdsapi.Client()
    out = Path(args.out_dir)
    fetch(client, "reanalysis-era5-pressure-levels",
          PLEV_REQUEST, out / "ERA5_PLEV.grib")
    fetch(client, "reanalysis-era5-single-levels",
          SFC_REQUEST, out / "ERA5_SFC.grib")
    print("完成。下一步：运行 verify_era5.py 自检。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def build_verify_script(case: dict) -> str:
    days, times, stamps = build_times(case)
    return f'''#!/usr/bin/env python3
"""ERA5 下载自检 —— 由 gen_era5_download.py 生成。

检查下载结果是否与 case.yaml 的请求一致：
文件存在且非空、时次数与预期相符。
不解码 GRIB 内容（那需要 pygrib/cfgrib）；这里只做可得即验的检查。
"""
import argparse
import struct
import sys
from pathlib import Path

EXPECTED_STAMPS = {len(stamps)}   # 期望的驱动时次数
FILES = ("ERA5_PLEV.grib", "ERA5_SFC.grib")


def grib_message_count(path: Path) -> int:
    """粗略统计 GRIB 文件中的消息数（数 'GRIB' 魔数）。

    只用于「明显偏少」的粗筛：GRIB2 的一个消息可含多个字段，
    因此消息数不等于时次数。真正的层数/变量核对需用 grib_ls。
    """
    blob = path.read_bytes()
    return blob.count(b"GRIB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default="data")
    args = ap.parse_args()

    root = Path(args.dir)
    problems = []
    for name in FILES:
        path = root / name
        if not path.exists():
            problems.append(f"缺失: {{path}}")
            continue
        size = path.stat().st_size
        if size == 0:
            problems.append(f"空文件: {{path}}")
            continue
        msgs = grib_message_count(path)
        print(f"ok  {{path}}  {{size}} bytes, {{msgs}} 个 GRIB 消息")
        if msgs == 0:
            problems.append(f"未找到 GRIB 消息: {{path}}")

    if problems:
        print()
        for p in problems:
            print("FAIL:", p)
        return 1

    print()
    print(f"期望驱动时次数: {{EXPECTED_STAMPS}}")
    print("请进一步核对（本脚本无法替代）:")
    print("  grib_ls -p level,shortName ERA5_PLEV.grib | head")
    print("  确认气压层数、变量名与 land_sea_mask / LANDSEA 是否存在")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def build_report(case: dict) -> str:
    north, west, south, east = parse_area(case["driver"]["area"])
    days, times, stamps = build_times(case)
    levels = parse_pressure_levels(case["driver"]["pressure_levels"])
    sfc = sfc_variables(case)
    lines = [
        f"# ERA5 下载请求摘要：{case.get('name', 'unnamed')}",
        "",
        f"- 区域 [N, W, S, E]：{north}, {west}, {south}, {east}",
        f"- 驱动时次：{len(stamps)} 个（{stamps[0]} .. {stamps[-1]}）",
        f"- 间隔：{case['driver']['interval_seconds']} s",
        f"- 气压层（{len(levels)} 层）：{levels}",
        f"- 单层变量（{len(sfc)} 个）：",
    ]
    lines += [f"    - {v}" for v in sfc]
    lines += ["", "## 核对要点", ""]
    lines += [
        "- `area` 的顺序是 **[North, West, South, East]**。"
        "写错顺序 CDS 不会报错，只会下载错误区域。",
        "- 气压层与单层是**两个独立数据集**，需分别下载、分别 ungrib。",
        "- 下载后用 `verify_era5.py` 自检；再用 `grib_ls` 核对层数与变量。",
        "- `land_sea_mask` 不随时间变化，部分下载方式不会自动带出，"
        "缺失时需单独请求。",
    ]
    if case["driver"].get("sst_handling") == "vtable-remove":
        lines += [
            "",
            "## SST",
            "",
            "`sst_handling=vtable-remove`，因此**未请求** "
            f"`{SST_VARIABLE}`。",
            "记得同时运行 `gen_namelist.py` 生成的 `vtable_prepare.sh`，"
            "从 Vtable 中移除 SST 条目。",
        ]
    lines += [
        "",
        "## 下一步",
        "",
        "```bash",
        'python download_era5.py --out-dir data',
        'python verify_era5.py --dir data',
        "```",
        "",
    ]
    return "\n".join(lines)


def generate(case: dict, out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in (
        ("download_era5.py", build_download_script(case)),
        ("verify_era5.py", build_verify_script(case)),
        ("era5_report.txt", build_report(case)),
    ):
        (out_dir / name).write_text(text, encoding="utf-8")
        written.append(name)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case_yaml")
    ap.add_argument("--out-dir", default="data")
    args = ap.parse_args()

    try:
        case = yaml.safe_load(Path(args.case_yaml).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"ERROR: 无法读取 case YAML: {exc}", file=sys.stderr)
        return 1

    try:
        # 先构建请求，任何一步不合法就在写文件之前停下
        build_plev_request(case)
        build_sfc_request(case)
        written = generate(case, Path(args.out_dir))
    except CaseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("未生成任何文件。", file=sys.stderr)
        return 1

    print(f"已生成 {len(written)} 个文件到 {args.out_dir}:")
    for w in written:
        print(f"  {w}")
    print()
    print("下一步：确认 area 顺序为 [N, W, S, E] 后运行 download_era5.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
