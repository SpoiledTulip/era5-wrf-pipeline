#!/usr/bin/env python3
"""从 case.yaml 生成 WRF 运行所需的 namelist 与 SLURM 作业脚本。

设计原则
--------
本脚本是**纯函数**：输入 case.yaml，输出文本文件。
不联网、不提交作业、不触碰任何远端环境。因此可以完全离线验证——
这正是它相对「智能体现场生成」的关键差别：
同一份配置，任何时候生成的 namelist 都逐字节相同，可复现、可审阅、可入版本控制。

生成的产物
----------
  namelist.wps        WPS 三段配置（geogrid / ungrib / metgrid）
  namelist.input      WRF 配置（仅在已知 num_metgrid_levels 时生成）
  wps.sbatch          WPS 作业脚本
  real.sbatch         real.exe 作业脚本（依赖 wps）
  wrf.sbatch          wrf.exe 作业脚本（依赖 real）
  submit_chain.sh     按依赖顺序提交三个作业
  vtable_prepare.sh   仅当 sst_handling=vtable-remove 时生成
  generation_report.txt  生成清单、待填占位符与仍需人工完成的步骤

站点私有字段以 @@NAME@@ 形式占位，须自行填写，
见 references/wrf-on-kunshan.md。占位符是刻意保留的：
不做静默填充，让未完成的部分在图上也看得见。
"""
from __future__ import annotations
import argparse
import copy
import re
from datetime import datetime, timedelta
from pathlib import Path
import sys

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import validate_case  # noqa: E402  复用同一套一致性校验

WRF_DATE = "%Y-%m-%d_%H:%M:%S"

# 站点私有字段的占位符（不会自动填充，需用户按站点配置替换）
SITE_PLACEHOLDERS = (
    "HPC_USER",         # 超算账号
    "HPC_WORK_ROOT",    # 远端案例工作根目录
    "SLURM_PARTITION",  # 计算分区
    "WPS_ROOT",         # WPS 安装路径
    "WRF_ROOT",         # WRF 安装路径
    "MODULE_LOAD",      # 模块加载块
    "NTASKS",           # MPI 进程数
    "WALLTIME",         # 各作业时限
)

_PROJ_MAP = {
    "lambert": "lambert",
    "polar": "polar",
    "mercator": "mercator",
    "lat-lon": "lat-lon",
    "latlon": "lat-lon",
}


class CaseError(Exception):
    """配置无法用于生成。"""


def _parse_dt(text: str) -> datetime:
    return datetime.strptime(text, WRF_DATE)


def _arr(values) -> str:
    """WRF namelist 的逗号列表，末尾补逗号。"""
    return ", ".join(str(v) for v in values) + ","


def _str_arr(values) -> str:
    """带引号的字符串列表，末尾补逗号（用于日期）。"""
    return ", ".join(f"'{v}'" for v in values) + ","


def _dates(case: dict) -> tuple[str, str]:
    start = _parse_dt(case["start_utc"])
    end = start + timedelta(hours=int(case["duration_hours"]))
    return start.strftime(WRF_DATE), end.strftime(WRF_DATE)


def _per_dom(value, n: int):
    """把物理方案标量展开成逐域数组。

    注意：不假设所有域用同一方案——若 case.yaml 已给出列表则原样使用。
    """
    if isinstance(value, (list, tuple)):
        if len(value) != n:
            raise CaseError(f"physics 列表长度 {len(value)} 与域数 {n} 不符")
        return list(value)
    return [value] * n


def build_namelist_wps(case: dict) -> str:
    dom = case["domain"]
    domains = dom["domains"]
    n = len(domains)
    start, end = _dates(case)
    proj = _PROJ_MAP.get(str(dom["projection"]).lower())
    if proj is None:
        raise CaseError(f"不支持的 projection: {dom['projection']}")

    e_we = [d["e_we"] for d in domains]
    e_sn = [d["e_sn"] for d in domains]
    pid = [d["parent_id"] for d in domains]
    ratio = [d["parent_grid_ratio"] for d in domains]
    ips = [d["i_parent_start"] for d in domains]
    jps = [d["j_parent_start"] for d in domains]
    geog_res = _per_dom(dom.get("geog_data_res", "default"), n)

    return f"""&share
 wrf_core             = 'ARW',
 max_dom              = {n},
 start_date           = {_str_arr([start] * n)}
 end_date             = {_str_arr([end] * n)}
 interval_seconds     = {int(case["driver"]["interval_seconds"])},
 io_form_geogrid      = 2,
 debug_level          = 0,
/

&geogrid
 parent_id            = {_arr(pid)}
 parent_grid_ratio    = {_arr(ratio)}
 i_parent_start       = {_arr(ips)}
 j_parent_start       = {_arr(jps)}
 e_we                 = {_arr(e_we)}
 e_sn                 = {_arr(e_sn)}
 geog_data_res        = {_str_arr(geog_res)}
 dx                   = {_arr([d["dx"] for d in domains])}
 dy                   = {_arr([d["dy"] for d in domains])}
 map_proj             = '{proj}',
 ref_lat              = {dom["ref_lat"]},
 ref_lon              = {dom["ref_lon"]},
 truelat1             = {dom["truelat1"]},
 truelat2             = {dom["truelat2"]},
 stand_lon            = {dom["stand_lon"]},
 geog_data_path       = '{dom["geog_data_path"]}',
 opt_geogrid_tbl_path = '@@WPS_ROOT@@/geogrid/',
/

&ungrib
 out_format           = 'WPS',
 prefix               = 'FILE',
/

&metgrid
 fg_name              = 'FILE',
 io_form_metgrid      = 2,
 opt_metgrid_tbl_path = '@@WPS_ROOT@@/metgrid',
/
"""


def build_namelist_input(case: dict, metgrid_levels: int) -> str:
    dom = case["domain"]
    domains = dom["domains"]
    n = len(domains)
    start, end = _dates(case)
    s, e = _parse_dt(start), _parse_dt(end)
    ph = case["physics"]
    vert = case["vertical"]

    def per(key):
        return _per_dom(ph[key], n)

    # radt 是辐射调用间隔（分钟），惯例取【最外层】网格的 dx（km）。
    # 注意是 domains[0] 而非最小 dx：最外层格距最大、要求辐射间隔也最大，
    # 按最细网格取值会让辐射调用过于频繁，白白拖慢积分。
    radt = max(1, int(float(domains[0]["dx"]) / 1000))
    hist = int(case["output_interval_minutes"])

    return f"""&time_control
 run_hours            = {int(case["duration_hours"])},
 start_year           = {_arr([s.year] + [e.year])}
 start_month          = {_arr([f"{s.month:02d}"] + [f"{e.month:02d}"])}
 start_day            = {_arr([f"{s.day:02d}"] + [f"{e.day:02d}"])}
 start_hour           = {_arr([f"{s.hour:02d}"] + [f"{e.hour:02d}"])}
 start_minute         = {_arr([f"{s.minute:02d}"] + [f"{e.minute:02d}"])}
 start_second         = {_arr([f"{s.second:02d}"] + [f"{e.second:02d}"])}
 end_year             = {_arr([s.year] + [e.year])}
 end_month            = {_arr([f"{s.month:02d}"] + [f"{e.month:02d}"])}
 end_day              = {_arr([f"{s.day:02d}"] + [f"{e.day:02d}"])}
 end_hour             = {_arr([f"{s.hour:02d}"] + [f"{e.hour:02d}"])}
 end_minute           = {_arr([f"{s.minute:02d}"] + [f"{e.minute:02d}"])}
 end_second           = {_arr([f"{s.second:02d}"] + [f"{e.second:02d}"])}
 interval_seconds     = {int(case["driver"]["interval_seconds"])},
 input_from_file      = {_arr([".true."] * n)}
 history_interval     = {_arr([hist] * n)}
 frames_per_outfile   = {_arr([1000] * n)}
 restart              = .false.,
 restart_interval     = 5000,
 io_form_history      = 2,
 io_form_restart      = 2,
 io_form_input        = 2,
 io_form_boundary     = 2,
 debug_level          = 0,
/

&domains
 time_step            = {int(case["time_step"])},
 time_step_fract_num  = 0,
 time_step_fract_den  = 1,
 max_dom              = {n},
 e_we                 = {_arr([d["e_we"] for d in domains])}
 e_sn                 = {_arr([d["e_sn"] for d in domains])}
 e_vert               = {_arr([vert["e_vert"]] * n)}
 p_top_requested      = {vert["p_top_requested"]},
 num_metgrid_levels   = {metgrid_levels},
 dx                   = {_arr([d["dx"] for d in domains])}
 dy                   = {_arr([d["dy"] for d in domains])}
 grid_id              = {_arr(list(range(1, n + 1)))}
 parent_id            = {_arr([d["parent_id"] for d in domains])}
 i_parent_start       = {_arr([d["i_parent_start"] for d in domains])}
 j_parent_start       = {_arr([d["j_parent_start"] for d in domains])}
 parent_grid_ratio    = {_arr([d["parent_grid_ratio"] for d in domains])}
 parent_time_step_ratio = {_arr([d["parent_grid_ratio"] for d in domains])}
 feedback             = 1,
 smooth_option        = 0,
/

&physics
 mp_physics           = {_arr(per("mp_physics"))}
 cu_physics           = {_arr(per("cu_physics"))}
 ra_lw_physics        = {_arr(per("ra_lw_physics"))}
 ra_sw_physics        = {_arr(per("ra_sw_physics"))}
 radt                 = {_arr([radt] * n)}
 sf_sfclay_physics    = {_arr(per("sf_sfclay_physics"))}
 sf_surface_physics   = {_arr(per("sf_surface_physics"))}
 bl_pbl_physics       = {_arr(per("bl_pbl_physics"))}
 bldt                 = {_arr([0] * n)}
 cudt                 = {_arr([5] * n)}
 num_land_cat         = 21,
 num_soil_layers      = 4,
 surface_input_source = 1,
/
"""


_SBATCH_HEADER = """#!/bin/bash
#SBATCH --job-name=@@CASE_NAME@@.{stage}
#SBATCH --partition=@@SLURM_PARTITION@@
#SBATCH --nodes=1
#SBATCH --ntasks=@@NTASKS@@
#SBATCH --time=@@WALLTIME_{upper}@@
#SBATCH --output=logs/{stage}.%j.out
#SBATCH --error=logs/{stage}.%j.err

set -euo pipefail
cd "@@HPC_WORK_ROOT@@/@@CASE_NAME@@/{stage}"

# ── 站点环境（按 references/wrf-on-kunshan.md 核对后填写）──
@@MODULE_LOAD@@
"""

_SBATCH_BODY = {
    "wps": """
# WPS: geogrid -> PLEV ungrib -> SFC ungrib -> metgrid
ln -sf "@@WPS_ROOT@@/ungrib/Variable_Tables/Vtable.ERA-interim.pl" Vtable 2>/dev/null || true

srun -n $SLURM_NTASKS "@@WPS_ROOT@@/geogrid.exe"
./link_grib.csh ../data/PLEV/*
srun -n $SLURM_NTASKS "@@WPS_ROOT@@/ungrib.exe"
cd ../wps_sfc && ./link_grib.csh ../data/SFC/* \\
  && srun -n $SLURM_NTASKS "@@WPS_ROOT@@/ungrib.exe" && cd ../wps
ln -sf ../wps_sfc/SFC:* .
srun -n $SLURM_NTASKS "@@WPS_ROOT@@/metgrid.exe"
""",
    "real": """
# real.exe（须在 WPS 成功后运行）
srun -n $SLURM_NTASKS "@@WRF_ROOT@@/run/real.exe"
""",
    "wrf": """
# wrf.exe（须在 real 成功后运行）
srun -n $SLURM_NTASKS "@@WRF_ROOT@@/run/wrf.exe"
""",
}


def build_sbatch(stage: str, case: dict) -> str:
    """生成单个作业脚本。stage 取 wps / real / wrf。"""
    if stage not in _SBATCH_BODY:
        raise CaseError(f"未知作业阶段: {stage}")
    header = _SBATCH_HEADER.format(stage=stage, upper=stage.upper())
    return header + _SBATCH_BODY[stage]


def build_submit_chain(case: dict) -> str:
    """按依赖顺序提交：wps -> real -> wrf。

    real 必须等 wps 成功（afterok），wrf 必须等 real 成功。
    上游失败时下游不提交，避免在错误的中间文件上继续算。
    """
    return """#!/bin/bash
# 按依赖顺序提交 WPS -> real -> WRF。
# 上游失败（afterok 未满足）时下游不会运行。
set -euo pipefail

mkdir -p logs

wps=$(sbatch --parsable wps.sbatch)
echo "wps   jobid=$wps"
real=$(sbatch --parsable --dependency=afterok:$wps real.sbatch)
echo "real  jobid=$real (depends on $wps)"
wrf=$(sbatch --parsable --dependency=afterok:$real wrf.sbatch)
echo "wrf   jobid=$wrf (depends on $real)"

echo
echo "check with:  squeue -u \\"${USER}\\""
echo "after done:  sacct -u \\"${USER}\\" -X"
"""


def build_vtable_prepare(case: dict) -> str:
    """sst_handling=vtable-remove 时生成 Vtable 准备脚本。

    ERA5 的 SST 在陆地上以 0 K 填充，细网格上会产生接近绝对零度的
    海岸带 2m 气温。SKINTEMP 在水上与 SST 一致，因此最简处理是移除 SST。
    见 references/era5-input-pitfalls.md
    """
    return """#!/bin/bash
# 从 WPS 的 Vtable.ERA-interim.pl 生成去掉 SST 的 Vtable。
# 原因：ERA5 的 SST 在陆地为 0 K 填充值，会让海岸线附近 2m 气温
# 接近 -273 degC（见 references/era5-input-pitfalls.md）。
set -euo pipefail

src="@@WPS_ROOT@@/ungrib/Variable_Tables/Vtable.ERA-interim.pl"
dst="./Vtable"

if [ ! -f "$src" ]; then
  echo "找不到 $src" >&2
  exit 1
fi

# 删掉名称以 SST 开头的行（保留 SKINTEMP 等其余条目）
grep -v -E '^[[:space:]]*SST[[:space:]]' "$src" > "$dst"

before=$(grep -c -E '^[[:space:]]*SST[[:space:]]' "$src" || true)
after=$(grep -c -E '^[[:space:]]*SST[[:space:]]' "$dst" || true)
echo "SST 条目: $before -> $after"
if [ "$after" -ne 0 ]; then
  echo "警告：仍存在 SST 条目，请人工核对 Vtable 格式" >&2
  exit 1
fi
echo "已生成 $dst"
"""


def build_report(case: dict, written: list[str], metgrid_levels: int | None,
                 placeholders: set[str]) -> str:
    lines = [
        f"# 生成报告：{case.get('name', 'unnamed')}",
        "",
        f"起点(UTC)：{case['start_utc']}   积分：{case['duration_hours']} h",
        f"域数：{len(case['domain']['domains'])}   "
        f"最细格距：{min(d['dx'] for d in case['domain']['domains'])} m",
        "",
        "## 已生成",
        "",
    ]
    lines += [f"- {w}" for w in written]
    lines += ["", "## 待填占位符", ""]
    if placeholders:
        lines += [f"- `@@{p}@@`" for p in sorted(placeholders)]
        lines += ["",
                  "这些是站点私有字段，需按 references/wrf-on-kunshan.md 填写。",
                  "**不会自动填充**——未替换的占位符会让作业直接失败，",
                  "好过被静默填入错误的路径。"]
    else:
        lines.append("- 无")

    lines += ["", "## 仍需人工完成", ""]
    if metgrid_levels is None:
        lines += [
            "- **namelist.input 未生成**：`num_metgrid_levels` 未确定。",
            "  WPS 完成后执行以下命令读取实际层数，再重新生成：",
            "  ```bash",
            "  ncdump -h met_em.d01.*.nc | grep num_metgrid_levels",
            "  python gen_namelist.py case.yaml --out-dir . --metgrid-levels <实际值>",
            "  ```",
        ]
    else:
        lines.append(f"- `num_metgrid_levels = {metgrid_levels}`（已写入 namelist.input）")

    sst = case["driver"].get("sst_handling")
    if sst == "vtable-remove":
        lines.append("- SST：运行 `vtable_prepare.sh` 生成去 SST 的 Vtable，"
                     "并在 WPS 前链接到 wps 目录")
    elif sst == "fill-missing":
        lines.append("- SST：在 `METGRID.TBL` 中给 SST 设 `fill_missing`（见 pitfalls 文档）")
    elif sst == "land-mask":
        lines.append("- SST：在 `METGRID.TBL` 中给 SST 加 "
                     "`interp_land_mask = LANDSEA(1)`（见 pitfalls 文档）")
    else:
        lines.append("- SST：`sst_handling` 未声明（仅粗网格可忽略；"
                     "见 references/era5-input-pitfalls.md）")

    lines += [
        "- 核对 `geog_data_path` 指向真实的地理数据目录（当前为 "
        f"`{case['domain']['geog_data_path']}`）",
        "- 确认 EXT 下载的 2D 变量清单完整且 `LANDSEA` 存在",
        "",
        "## 下一步",
        "",
        "```bash",
        "bash submit_chain.sh     # 按 wps -> real -> wrf 依赖顺序提交",
        "squeue -u $USER          # 查看队列",
        "sacct -u $USER -X        # 查看已结束作业",
        "```",
        "",
        "作业失败时按 references/rsl-error-troubleshooting.md 的 A/B/C 分类处理。",
        "",
        "> 本报告由 gen_namelist.py 生成。脚本是纯函数，不联网、不提交作业。",
        "",
    ]
    return "\n".join(lines)


def generate(case: dict, out_dir: Path, metgrid_levels: int | None) -> list[str]:
    """生成全部产物，返回已写出的文件名列表。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    placeholders: set[str] = set()

    def write(name: str, text: str) -> None:
        (out_dir / name).write_text(text, encoding="utf-8")
        written.append(name)
        placeholders.update(re.findall(r"@@([A-Z_]+)@@", text))

    write("namelist.wps", build_namelist_wps(case))
    if metgrid_levels is not None:
        write("namelist.input", build_namelist_input(case, metgrid_levels))

    for stage in ("wps", "real", "wrf"):
        write(f"{stage}.sbatch", build_sbatch(stage, case))
    write("submit_chain.sh", build_submit_chain(case))

    if case["driver"].get("sst_handling") == "vtable-remove":
        write("vtable_prepare.sh", build_vtable_prepare(case))

    # 报告最后写：它需要知道前面写了什么
    report = build_report(case, written, metgrid_levels, placeholders)
    (out_dir / "generation_report.txt").write_text(report, encoding="utf-8")
    written.append("generation_report.txt")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case_yaml")
    ap.add_argument("--out-dir", default=".",
                    help="输出目录（默认当前目录）")
    ap.add_argument("--metgrid-levels", type=int, default=None,
                    help="met_em 的实际垂直层数；未给则读 case.yaml，"
                         "都缺则只生成 namelist.wps")
    args = ap.parse_args()

    try:
        case = yaml.safe_load(Path(args.case_yaml).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"ERROR: 无法读取 case YAML: {exc}", file=sys.stderr)
        return 1

    # 先跑一致性校验：配置本身有问题时直接停，不生成任何文件。
    # 注意：若用户已通过 --metgrid-levels 给出实测层数，把它并入校验用的副本——
    # 这正是「WPS 后填入实际层数」那一步，等价于已写入 case.yaml。
    resolved = copy.deepcopy(case)
    if args.metgrid_levels is not None:
        resolved.setdefault("vertical", {})["num_metgrid_levels"] = args.metgrid_levels
    errors, warnings = validate_case.validate(resolved, args.metgrid_levels)
    for w in warnings:
        print(f"WARNING: {w}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        print("配置未通过校验，未生成任何文件。", file=sys.stderr)
        return 1

    levels = args.metgrid_levels
    if levels is None:
        levels = case.get("vertical", {}).get("num_metgrid_levels")

    try:
        written = generate(case, Path(args.out_dir), levels)
    except CaseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"已生成 {len(written)} 个文件到 {args.out_dir}:")
    for w in written:
        print(f"  {w}")
    if levels is None:
        print()
        print("未生成 namelist.input：num_metgrid_levels 未知。")
        print("WPS 完成后用 --metgrid-levels <实际值> 重新运行。")
    print()
    print("下一步：填写生成报告中的 @@占位符@@，再 bash submit_chain.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
