"""gen_namelist.py 的测试。

做法：把生成的 namelist 解析成 dict 再断言字段值，
而不是用 subprocess 匹配子串——字符串匹配会漏掉语义错误
（例如 e_we 在 wps 与 input 里数值不一致，两处都"包含该行"）。

本文件本身就是这个 skill 的核心主张的示例：
**能离线证明的事，就该写成测试。**
"""
from __future__ import annotations
import copy
import re
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "era5-wrf-pipeline" / "scripts"))
import gen_namelist  # noqa: E402

EXAMPLE = ROOT / "examples" / "case.example.yaml"


def parse_namelist(text: str) -> dict[str, dict[str, str]]:
    """把 Fortran namelist 文本解析成 {section: {key: raw_value}}。

    只处理本生成器会产出的简单形式：等号赋值、逗号分隔、行内 ! 注释。
    字符串值里的引号原样保留，便于断言。
    """
    out: dict[str, dict[str, str]] = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        if line.startswith("&"):
            section = line[1:].split()[0]
            out[section] = {}
            continue
        if line.startswith("/"):
            section = None
            continue
        if section and "=" in line:
            key, value = line.split("=", 1)
            value = value.split("!")[0].strip().rstrip(",").strip()
            out[section][key.strip()] = value
    return out


def as_ints(raw: str) -> list[int]:
    return [int(x) for x in raw.split(",") if x.strip()]


def as_strs(raw: str) -> list[str]:
    return [x.strip().strip("'") for x in raw.split(",") if x.strip()]


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.case = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
        self.wps = parse_namelist(gen_namelist.build_namelist_wps(self.case))
        self.input_text = gen_namelist.build_namelist_input(self.case, 38)
        self.input = parse_namelist(self.input_text)

    # ---------- 跨文件一致性（WRF 最常见的报错来源）----------

    def test_max_dom_matches_between_wps_and_input(self):
        self.assertEqual(self.wps["share"]["max_dom"], self.input["domains"]["max_dom"])

    def test_e_we_identical_between_wps_and_input(self):
        """e_we 两处不一致是 real.exe 直接报错的经典原因。"""
        self.assertEqual(as_ints(self.wps["geogrid"]["e_we"]),
                         as_ints(self.input["domains"]["e_we"]))

    def test_e_sn_identical_between_wps_and_input(self):
        self.assertEqual(as_ints(self.wps["geogrid"]["e_sn"]),
                         as_ints(self.input["domains"]["e_sn"]))

    def test_dx_dy_identical_between_wps_and_input(self):
        for key in ("dx", "dy"):
            self.assertEqual(as_ints(self.wps["geogrid"][key]),
                             as_ints(self.input["domains"][key]), key)

    def test_interval_seconds_identical(self):
        self.assertEqual(self.wps["share"]["interval_seconds"],
                         self.input["time_control"]["interval_seconds"])

    def test_nesting_identical(self):
        for key in ("parent_id", "i_parent_start", "j_parent_start",
                    "parent_grid_ratio"):
            self.assertEqual(as_ints(self.wps["geogrid"][key]),
                             as_ints(self.input["domains"][key]), key)

    def test_end_date_matches_start_plus_duration(self):
        case = self.case
        start = gen_namelist._parse_dt(case["start_utc"])
        expected = (start + __import__("datetime").timedelta(
            hours=int(case["duration_hours"]))).strftime("%Y-%m-%d_%H:%M:%S")
        self.assertEqual(as_strs(self.wps["share"]["end_date"])[0], expected)

    def test_wps_and_input_dates_agree(self):
        """namelist.wps 的 start_date 必须与 namelist.input 的 start_* 对上。"""
        y, m, d = (as_strs(self.wps["share"]["start_date"])[0]
                   .split("_")[0].split("-"))
        tc = self.input["time_control"]
        self.assertEqual(as_ints(tc["start_year"])[0], int(y))
        self.assertEqual(int(tc["start_month"].split(",")[0]), int(m))
        self.assertEqual(int(tc["start_day"].split(",")[0]), int(d))

    # ---------- 逐域展开 ----------

    def test_physics_expanded_per_domain(self):
        n = len(self.case["domain"]["domains"])
        for key in ("mp_physics", "cu_physics", "bl_pbl_physics",
                    "ra_lw_physics", "ra_sw_physics"):
            self.assertEqual(len(as_ints(self.input["physics"][key])), n, key)

    def test_physics_values_come_from_case(self):
        for key, want in self.case["physics"].items():
            self.assertEqual(as_ints(self.input["physics"][key])[0], want, key)

    def test_physics_list_length_mismatch_rejected(self):
        self.case["physics"]["mp_physics"] = [6, 6, 6]  # 域只有 2 个
        with self.assertRaises(gen_namelist.CaseError):
            gen_namelist.build_namelist_input(self.case, 38)

    def test_vertical_and_metgrid_levels(self):
        d = self.input["domains"]
        self.assertEqual(as_ints(d["num_metgrid_levels"])[0], 38)
        self.assertEqual(as_ints(d["e_vert"])[0], self.case["vertical"]["e_vert"])
        self.assertEqual(int(float(d["p_top_requested"])),
                         self.case["vertical"]["p_top_requested"])

    def test_time_step_from_case(self):
        self.assertEqual(as_ints(self.input["domains"]["time_step"])[0],
                         self.case["time_step"])

    def test_history_interval_from_output_interval(self):
        self.assertEqual(as_ints(self.input["time_control"]["history_interval"])[0],
                         self.case["output_interval_minutes"])

    def test_radt_scales_with_dx(self):
        """radt 通常取最外层格距（km）。15 km -> 15。"""
        self.assertEqual(as_ints(self.input["physics"]["radt"])[0], 15)

    def test_projection_mapping(self):
        self.assertEqual(self.wps["geogrid"]["map_proj"], "'lambert'")
        self.case["domain"]["projection"] = "mercator"
        self.assertEqual(
            parse_namelist(gen_namelist.build_namelist_wps(self.case))
            ["geogrid"]["map_proj"], "'mercator'")

    def test_unknown_projection_rejected(self):
        self.case["domain"]["projection"] = "warp-drive"
        with self.assertRaises(gen_namelist.CaseError):
            gen_namelist.build_namelist_wps(self.case)


class SbatchTests(unittest.TestCase):
    def setUp(self):
        self.case = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))

    def test_each_stage_generated(self):
        for stage in ("wps", "real", "wrf"):
            text = gen_namelist.build_sbatch(stage, self.case)
            self.assertIn("#!/bin/bash", text)
            self.assertIn(f"logs/{stage}.%j.out", text)
            self.assertIn("@@MODULE_LOAD@@", text)

    def test_no_runs_on_login_node(self):
        """所有重计算必须走 srun/sbatch，不得裸执行可执行文件。"""
        for stage in ("wps", "real", "wrf"):
            text = gen_namelist.build_sbatch(stage, self.case)
            for line in text.splitlines():
                s = line.strip()
                if s.startswith(("geogrid.exe", "ungrib.exe", "metgrid.exe",
                                 "real.exe", "wrf.exe", "./wrf.exe")):
                    self.fail(f"{stage}.sbatch 在登录节点裸跑可执行文件: {s}")
            self.assertNotIn("mpirun -np 1 ./", text)

    def test_wrf_stage_uses_srun(self):
        text = gen_namelist.build_sbatch("wrf", self.case)
        self.assertIn("srun -n $SLURM_NTASKS", text)
        self.assertIn("wrf.exe", text)

    def test_unknown_stage_rejected(self):
        with self.assertRaises(gen_namelist.CaseError):
            gen_namelist.build_sbatch("postproc", self.case)

    def test_submit_chain_orders_dependencies(self):
        """wps -> real -> wrf，且 real/wrf 用 afterok 依赖。"""
        text = gen_namelist.build_submit_chain(self.case)
        self.assertIn("--dependency=afterok:$wps", text)
        self.assertIn("--dependency=afterok:$real", text)
        self.assertLess(text.index("wps.sbatch"), text.index("real.sbatch"))
        self.assertLess(text.index("real.sbatch"), text.index("wrf.sbatch"))
        self.assertIn("--parsable", text)


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.case = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))

    def test_writes_expected_files(self):
        with tempfile.TemporaryDirectory() as d:
            written = gen_namelist.generate(self.case, Path(d), 38)
            for name in ("namelist.wps", "namelist.input", "wps.sbatch",
                         "real.sbatch", "wrf.sbatch", "submit_chain.sh",
                         "generation_report.txt"):
                self.assertIn(name, written)
                self.assertTrue((Path(d) / name).is_file(), name)

    def test_no_input_namelist_without_levels(self):
        """层数未知时不应生成 namelist.input——否则会写出错误的层数。"""
        with tempfile.TemporaryDirectory() as d:
            written = gen_namelist.generate(self.case, Path(d), None)
            self.assertNotIn("namelist.input", written)
            self.assertFalse((Path(d) / "namelist.input").exists())
            report = (Path(d) / "generation_report.txt").read_text(encoding="utf-8")
            self.assertIn("num_metgrid_levels", report)
            self.assertIn("--metgrid-levels", report)

    def test_vtable_script_only_for_vtable_remove(self):
        with tempfile.TemporaryDirectory() as d:
            gen_namelist.generate(self.case, Path(d), 38)
            self.assertFalse((Path(d) / "vtable_prepare.sh").exists())

            case = copy.deepcopy(self.case)
            case["driver"]["sst_handling"] = "vtable-remove"
            gen_namelist.generate(case, Path(d), 38)
            script = (Path(d) / "vtable_prepare.sh").read_text(encoding="utf-8")
            self.assertIn("Vtable.ERA-interim.pl", script)
            self.assertIn("grep -v", script)

    def test_report_lists_placeholders(self):
        with tempfile.TemporaryDirectory() as d:
            gen_namelist.generate(self.case, Path(d), 38)
            report = (Path(d) / "generation_report.txt").read_text(encoding="utf-8")
            for token in ("@@WPS_ROOT@@", "@@WRF_ROOT@@", "@@SLURM_PARTITION@@"):
                self.assertIn(token, report, token)

    def test_deterministic(self):
        """同一份配置生成两次必须逐字节相同——这是可复现的前提。"""
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            gen_namelist.generate(self.case, Path(d1), 38)
            gen_namelist.generate(self.case, Path(d2), 38)
            for name in ("namelist.wps", "namelist.input", "wps.sbatch",
                         "generation_report.txt"):
                self.assertEqual((Path(d1) / name).read_bytes(),
                                 (Path(d2) / name).read_bytes(), name)


class FailLoudlyTests(unittest.TestCase):
    """配置无效时必须拒绝生成，而不是生成一份看着正常的配置。"""

    def setUp(self):
        self.case = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))

    def _validate(self, case, levels):
        resolved = copy.deepcopy(case)
        if levels is not None:
            resolved.setdefault("vertical", {})["num_metgrid_levels"] = levels
        return gen_namelist.validate_case.validate(resolved, levels)

    def test_invalid_grid_ratio_rejected(self):
        self.case["domain"]["domains"][1]["e_we"] = 137  # 不整除
        errors, _ = self._validate(self.case, 38)
        self.assertTrue(errors)

    def test_child_outside_parent_rejected(self):
        self.case["domain"]["domains"][1]["i_parent_start"] = 1
        errors, _ = self._validate(self.case, 38)
        self.assertTrue(errors)

    def test_sst_warning_for_fine_era5_grid(self):
        errors, warnings = self._validate(self.case, 38)
        self.assertEqual(errors, [])
        self.assertTrue(any("sst_handling" in w for w in warnings))


if __name__ == "__main__":
    unittest.main(verbosity=2)
