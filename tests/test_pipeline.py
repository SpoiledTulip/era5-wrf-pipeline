from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "era5-wrf-pipeline" / "scripts"))
import validate_case
import extract_wrf


class CaseTests(unittest.TestCase):
    def setUp(self):
        self.case = yaml.safe_load((ROOT / "examples" / "case.example.yaml").read_text(encoding="utf-8"))

    def test_example_precheck(self):
        errors, warnings = validate_case.validate(self.case)
        self.assertEqual(errors, [])
        self.assertTrue(warnings)

    def test_observed_levels(self):
        self.case["vertical"]["num_metgrid_levels"] = 10
        self.assertEqual(validate_case.validate(self.case, 10)[0], [])
        self.assertTrue(validate_case.validate(self.case, 11)[0])
        self.case["vertical"]["num_metgrid_levels"] = None
        self.assertTrue(validate_case.validate(self.case, 10)[0])

    def test_invalid_cases(self):
        cases = [
            ("ratio zero", lambda d: d["domain"]["domains"][1].update(parent_grid_ratio=0)),
            ("parent forward", lambda d: d["domain"]["domains"][1].update(parent_id=2)),
            ("child boundary", lambda d: d["domain"]["domains"][1].update(i_parent_start=1)),
            ("mesh ratio", lambda d: d["domain"]["domains"][1].update(e_we=137)),
            ("top coverage", lambda d: d["vertical"].update(p_top_requested=1000)),
            ("duration", lambda d: d.update(duration_hours=73)),
            ("interval", lambda d: d["driver"].update(interval_seconds=0)),
            ("end date", lambda d: d.update(end_utc="2026-08-09_00:00:00")),
            ("missing field", lambda d: d.pop("domain")),
        ]
        for name, mutate in cases:
            with self.subTest(name=name):
                data = deepcopy(self.case)
                mutate(data)
                self.assertTrue(validate_case.validate(data)[0])
        self.assertTrue(validate_case.validate(None)[0])

    def test_time_step_warning(self):
        self.case["time_step"] = 120
        errors, warnings = validate_case.validate(self.case)
        self.assertEqual(errors, [])
        self.assertTrue(any("time_step" in w for w in warnings))


class ExtractionTests(unittest.TestCase):
    def test_pressure_level_units_time_and_missing(self):
        pressure = np.ones((2, 3, 4)) * 500
        getvar = Mock(return_value=pressure)
        interpolate = Mock(return_value=np.ma.array(np.ones((3, 4)), mask=True))
        fake_wrf = SimpleNamespace(interplevel=interpolate)
        with patch.dict(sys.modules, {"wrf": fake_wrf}):
            out = extract_wrf._at_level(pressure, "dataset", getvar, 500, 2)
        getvar.assert_called_once_with("dataset", "pressure", timeidx=2)
        self.assertEqual(interpolate.call_args.args[2], 500)
        self.assertTrue(np.isnan(out).all())

    def test_surface_units(self):
        self.assertAlmostEqual(extract_wrf._field(None, lambda *a, **k: np.array(300.),
                                                  "t2", 0, None), 26.85)
        uv = np.array([np.ones((2, 2))*3, np.ones((2, 2))*4])
        np.testing.assert_allclose(extract_wrf._field(None, lambda *a, **k: uv,
                                                     "uvmet10", 0, None), 5)
        getvar = Mock(return_value=np.ones((2, 2)))
        np.testing.assert_allclose(extract_wrf._field(None, getvar, "rain", 0, None), 2)
        self.assertEqual([c.args[1] for c in getvar.call_args_list], ["RAINC", "RAINNC"])

    def test_plane_npz_adapter(self):
        # Verify serialization against a fake dataset, not WRF diagnostics.
        lon, lat = np.meshgrid(np.arange(4.), np.arange(3.))
        ds = SimpleNamespace(
            variables={"XLAT": lat[None], "XLONG": lon[None],
                       "Times": np.array([list("2026-08-05_00:00:00")], dtype="S1")},
            dimensions={"Time": [0]}, close=lambda: None)
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "nested" / "field.npz"
            args = SimpleNamespace(wrfout="fake", time=-1, var="slp", level=None,
                                   with_wind=False, radius=None, lat=None, lon=None, out=str(out))
            with patch.object(extract_wrf, "_load", return_value=(ds, lambda *a, **k: np.ones((3, 4))*1000)):
                self.assertEqual(extract_wrf.cmd_plane(args), 0)
            with np.load(out, allow_pickle=False) as data:
                np.testing.assert_allclose(data["field"], 1000)
                np.testing.assert_array_equal(data["lon"], lon)
                self.assertEqual(data["time_index"][0], 0)

    def test_stamp(self):
        ds = SimpleNamespace(variables={"Times": np.array([list("2026-08-05_00:00:00")], dtype="S1")})
        self.assertEqual(extract_wrf._stamp(ds, 0), "2026-08-05_00:00:00")


class PlotTests(unittest.TestCase):
    def test_offline_demo_nonblank(self):
        import matplotlib.image as image
        with tempfile.TemporaryDirectory() as folder:
            subprocess.run([sys.executable, str(ROOT / "examples" / "offline_demo.py"),
                            "--out-dir", folder], check=True)
            pixels = image.imread(Path(folder) / "synthetic_slp.png")
            self.assertGreater(pixels.shape[0], 500)
            self.assertGreater(float(pixels[..., :3].std()), 0.05)
            with np.load(Path(folder) / "synthetic_slp.npz", allow_pickle=False) as data:
                self.assertEqual(data["field"].shape, (49, 49))
                self.assertIn("synthetic", str(data["source"]))


if __name__ == "__main__":
    unittest.main()
