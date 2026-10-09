"""gen_era5_download.py 的测试。

核心在 AreaOrderTests：CDS 的 area 是 [North, West, South, East]，
顺序写错不会报错，只会安静地下载错误区域——
这类"跑通但结果错"的问题只能靠断言拦住。
"""
from __future__ import annotations
import copy
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "era5-wrf-pipeline" / "scripts"))
import gen_era5_download as g  # noqa: E402

EXAMPLE = ROOT / "examples" / "case.example.yaml"


class AreaOrderTests(unittest.TestCase):
    def setUp(self):
        self.case = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))

    def test_example_area_is_valid_nwse(self):
        north, west, south, east = g.parse_area(self.case["driver"]["area"])
        self.assertEqual((north, west, south, east), (39.0, 104.0, 17.0, 141.0))

    def test_reversed_latitude_rejected(self):
        """把 [N,W,S,E] 写成 [S,W,N,E] 是最容易犯的错。"""
        self.case["driver"]["area"] = [17, 104, 39, 141]
        with self.assertRaises(g.CaseError) as ctx:
            g.parse_area(self.case["driver"]["area"])
        self.assertIn("North", str(ctx.exception))

    def test_reversed_longitude_rejected(self):
        self.case["driver"]["area"] = [39, 141, 17, 104]
        with self.assertRaises(g.CaseError):
            g.parse_area(self.case["driver"]["area"])

    def test_swapped_nw_rejected(self):
        """[W, N, S, E] 顺序错位。"""
        self.case["driver"]["area"] = [104, 39, 141, 17]
        with self.assertRaises(g.CaseError):
            g.parse_area(self.case["driver"]["area"])

    def test_equal_bounds_rejected(self):
        with self.assertRaises(g.CaseError):
            g.parse_area([39, 104, 39, 141])

    def test_wrong_length_rejected(self):
        for bad in ([39, 104], [39, 104, 17, 141, 5], "39,104,17,141", None):
            with self.assertRaises(g.CaseError, msg=repr(bad)):
                g.parse_area(bad)

    def test_out_of_range_rejected(self):
        with self.assertRaises(g.CaseError):
            g.parse_area([95, 104, 17, 141])       # 纬度 > 90
        with self.assertRaises(g.CaseError):
            g.parse_area([39, 104, 17, 200])       # 经度 > 180

    def test_request_preserves_nwse_order(self):
        req = g.build_plev_request(self.case)
        self.assertEqual(req["area"], [39.0, 104.0, 17.0, 141.0])

    def test_negative_longitude_region_ok(self):
        """西半球区域（如美国）—— west 为负是合法的。"""
        north, west, south, east = g.parse_area([50, -125, 25, -66])
        self.assertEqual((north, west, south, east), (50.0, -125.0, 25.0, -66.0))


class PressureLevelTests(unittest.TestCase):
    def test_sorted_descending(self):
        levels = g.parse_pressure_levels([500, 1000, 850])
        self.assertEqual(levels, [1000, 850, 500])

    def test_duplicates_rejected(self):
        with self.assertRaises(g.CaseError):
            g.parse_pressure_levels([1000, 1000, 500])

    def test_nonpositive_rejected(self):
        with self.assertRaises(g.CaseError):
            g.parse_pressure_levels([1000, 0])

    def test_empty_rejected(self):
        with self.assertRaises(g.CaseError):
            g.parse_pressure_levels([])

    def test_request_levels_are_strings(self):
        case = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
        req = g.build_plev_request(case)
        self.assertTrue(all(isinstance(p, str) for p in req["pressure_level"]))
        self.assertEqual(req["pressure_level"][0], "1000")


class TimeWindowTests(unittest.TestCase):
    def setUp(self):
        self.case = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))

    def test_stamp_count_matches_window(self):
        """72 h / 6 h = 12 段，含两端共 13 个时次。"""
        _, _, stamps = g.build_times(self.case)
        self.assertEqual(len(stamps), 13)
        self.assertEqual(stamps[0], "2026-08-05_00:00:00")
        self.assertEqual(stamps[-1], "2026-08-08_00:00:00")

    def test_last_stamp_equals_end(self):
        _, _, stamps = g.build_times(self.case)
        self.assertTrue(stamps[-1].endswith("00:00:00"))

    def test_unaligned_duration_rejected(self):
        """窗口不能被间隔整除时，末时刻会缺失——必须报错而非静默少下。"""
        self.case["duration_hours"] = 73
        with self.assertRaises(g.CaseError):
            g.build_times(self.case)

    def test_non_hour_interval_rejected(self):
        self.case["driver"]["interval_seconds"] = 1800
        with self.assertRaises(g.CaseError):
            g.build_times(self.case)

    def test_days_and_times_deduplicated(self):
        days, times, _ = g.build_times(self.case)
        self.assertEqual(days, ["2026-08-05", "2026-08-06",
                                "2026-08-07", "2026-08-08"])
        self.assertEqual(times, ["00:00", "06:00", "12:00", "18:00"])

    def test_hourly_interval(self):
        case = copy.deepcopy(self.case)
        case["driver"]["interval_seconds"] = 3600
        days, times, stamps = g.build_times(case)
        self.assertEqual(len(stamps), 73)
        self.assertEqual(len(times), 24)


class VariableListTests(unittest.TestCase):
    def setUp(self):
        self.case = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))

    def test_sfc_includes_land_sea_mask(self):
        """LANDSEA 缺失会让 SST 的陆海掩膜方案失效，必须请求。"""
        self.assertIn("land_sea_mask", g.sfc_variables(self.case))

    def test_sfc_includes_four_soil_layers(self):
        v = g.sfc_variables(self.case)
        for i in range(1, 5):
            self.assertIn(f"soil_temperature_level_{i}", v)
            self.assertIn(f"volumetric_soil_water_layer_{i}", v)

    def test_sst_dropped_when_vtable_remove(self):
        """sst_handling=vtable-remove 时应跳过 SST 请求，避免无用下载。"""
        self.case["driver"]["sst_handling"] = "vtable-remove"
        self.assertNotIn(g.SST_VARIABLE, g.sfc_variables(self.case))
        self.assertNotIn(g.SST_VARIABLE, g.build_sfc_request(self.case)["variable"])

    def test_sst_kept_otherwise(self):
        for value in (None, "fill-missing", "land-mask"):
            case = copy.deepcopy(self.case)
            case["driver"]["sst_handling"] = value
            self.assertIn(g.SST_VARIABLE, g.sfc_variables(case), repr(value))

    def test_plev_variables_complete(self):
        req = g.build_plev_request(self.case)
        for v in ("geopotential", "temperature", "relative_humidity",
                  "specific_humidity", "u_component_of_wind",
                  "v_component_of_wind"):
            self.assertIn(v, req["variable"], v)


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.case = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))

    def test_writes_expected_files(self):
        with tempfile.TemporaryDirectory() as d:
            written = g.generate(self.case, Path(d))
            for name in ("download_era5.py", "verify_era5.py", "era5_report.txt"):
                self.assertIn(name, written)
                self.assertTrue((Path(d) / name).is_file(), name)

    def test_generated_script_is_valid_python(self):
        """生成的下载脚本必须能通过语法检查，否则用户拿到的是坏文件。"""
        import ast
        with tempfile.TemporaryDirectory() as d:
            g.generate(self.case, Path(d))
            for name in ("download_era5.py", "verify_era5.py"):
                src = (Path(d) / name).read_text(encoding="utf-8")
                ast.parse(src)  # 语法错误会抛异常

    def test_download_script_is_idempotent(self):
        """脚本必须跳过已存在且非空的文件，否则重跑会重复下载。"""
        src = g.build_download_script(self.case)
        self.assertIn("exists()", src)
        self.assertIn("st_size > 0", src)

    def test_report_mentions_area_order_trap(self):
        report = g.build_report(self.case)
        self.assertIn("North, West, South, East", report)

    def test_report_notes_sst_skip(self):
        case = copy.deepcopy(self.case)
        case["driver"]["sst_handling"] = "vtable-remove"
        report = g.build_report(case)
        self.assertIn("未请求", report)
        self.assertIn("vtable_prepare.sh", report)

    def test_deterministic(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            g.generate(self.case, Path(d1))
            g.generate(self.case, Path(d2))
            for name in ("download_era5.py", "era5_report.txt"):
                self.assertEqual((Path(d1) / name).read_bytes(),
                                 (Path(d2) / name).read_bytes(), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
