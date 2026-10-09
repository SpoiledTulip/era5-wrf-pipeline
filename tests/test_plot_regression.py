"""回归测试：守住 wxplot.china_map 的三个已确认缺陷。

为什么原 test_pipeline.py 9 个测试全绿却漏掉这些？
因为它只断言"图不是空白"，从没断言
"底图应该有色""国界应该有 N 条""命中 0 条应该报错"。
—— 测试只保护它断言过的东西。

这些测试在修复前 FAIL，修复后 PASS：
  BUG-1 底图配色失效（setattr 无效）
  BUG-2 国界全丢（admin_0 文件没有 ADM0_NAME 字段）
  BUG-3 静默失败（命中 0 条不报警）

需要真实矢量时设环境变量：
  GIS_ROOT=<含 ne_10m_admin0/ 与 ne_10m_admin1/ 的目录>
未设置时相关集成测试自动跳过。
"""
from __future__ import annotations
import os
import sys
import unittest
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.io.shapereader as shpreader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "era5-wrf-pipeline" / "scripts"))
import wxplot  # noqa: E402

GIS_ROOT = os.environ.get("GIS_ROOT")


class FeatureStyleTests(unittest.TestCase):
    """BUG-1：底图配色必须真的生效。"""

    def test_style_reaches_constructor_kwargs(self):
        """颜色必须进入构造 kwargs（cartopy 绘制时只读这里）。"""
        feat = wxplot._make_feature("land", "10m", facecolor="#f5f0e6")
        self.assertEqual(feat._kwargs.get("facecolor"), "#f5f0e6",
                         "facecolor 未进入 _kwargs → 底图将是无色的")

    def test_coastline_defaults_to_no_fill(self):
        feat = wxplot._make_feature("coastline", "10m", edgecolor="#333333")
        self.assertEqual(feat._kwargs.get("facecolor"), "none")

    def test_drawn_feature_has_nonempty_facecolor(self):
        """端到端：add_feature 后 Artist 必须有非空填充色。"""
        fig = plt.figure()
        ax = fig.add_subplot(111, projection=ccrs.PlateCarree())
        ax.add_feature(wxplot._make_feature("land", "10m",
                                            facecolor="#f5f0e6"), zorder=0)
        faces = [len(a.get_facecolor()) for a in ax.get_children()
                 if type(a).__name__ == "FeatureArtist"]
        # 有缺陷的实现这里全是空列表 → 断言失败
        self.assertTrue(any(n > 0 for n in faces),
                        "所有底图要素填充色为空 → BUG-1 复现")
        plt.close(fig)

    def test_no_setattr_on_feature(self):
        """回归防线：china_map 源码里不应再出现对要素 setattr 样式。"""
        src = (ROOT / "skills" / "era5-wrf-pipeline" / "scripts" / "wxplot.py").read_text(
            encoding="utf-8")
        self.assertNotIn("setattr(f", src,
                         "要素样式又改成了事后 setattr，会静默失效")


class ChinaBorderMatchingTests(unittest.TestCase):
    """BUG-2：不同矢量文件的判定字段名不同，必须各自配对。"""

    def test_admin0_uses_left_right_not_adm0_name(self):
        """国界文件没有 ADM0_NAME，必须靠 ADM0_LEFT / ADM0_RIGHT。"""
        keys = ("adm0_left", "adm0_right")
        self.assertTrue(wxplot._is_china({"ADM0_LEFT": "China"}, keys))
        self.assertTrue(wxplot._is_china({"ADM0_RIGHT": "China"}, keys))
        # 原实现用 ADM0_NAME，永远命中不了
        self.assertFalse(wxplot._is_china({"ADM0_NAME": "China"}, keys))

    def test_admin1_uses_adm0_name(self):
        keys = ("adm0_name",)
        self.assertTrue(wxplot._is_china({"ADM0_NAME": "China"}, keys))
        self.assertFalse(wxplot._is_china({"ADM0_NAME": "Japan"}, keys))

    def test_field_name_case_insensitive(self):
        self.assertTrue(wxplot._is_china({"adm0_name": "china"}, ("adm0_name",)))
        self.assertTrue(wxplot._is_china({"ADM0_NAME": "China"}, ("adm0_name",)))

    def test_empty_or_none_attributes_never_crash(self):
        self.assertFalse(wxplot._is_china({}, ("adm0_left",)))
        self.assertFalse(wxplot._is_china(None, ("adm0_name",)))

    def test_boundary_table_matches_each_file(self):
        """国界表必须为自己那类文件配正确的字段，不能共用同一字段集。"""
        table = {os.path.basename(rel): keys
                 for rel, _c, _w, keys in wxplot.BOUNDARY_FILES}
        admin0 = table["ne_10m_admin_0_boundary_lines_land.shp"]
        self.assertIn("adm0_left", admin0)
        self.assertNotIn("adm0_name", admin0,
                         "admin_0 文件没有 ADM0_NAME，不能配这个字段")

    @unittest.skipUnless(GIS_ROOT, "需设置 GIS_ROOT 指向 Natural Earth 矢量目录")
    def test_admin0_actually_matches_china(self):
        """真实矢量验证：国界文件必须能筛出中国的边界（>0 条）。"""
        path = os.path.join(
            GIS_ROOT, "ne_10m_admin0/ne_10m_admin_0_boundary_lines_land.shp")
        if not os.path.exists(path):
            self.skipTest(f"缺 {path}")
        keys = ("adm0_left", "adm0_right")
        hit = sum(1 for r in shpreader.Reader(path).records()
                  if wxplot._is_china(r.attributes, keys))
        self.assertGreater(hit, 0,
                           "国界命中 0 条 → 图上将看不到国界（BUG-2 复现）")

    @unittest.skipUnless(GIS_ROOT, "需设置 GIS_ROOT")
    def test_admin1_actually_matches_china(self):
        path = os.path.join(
            GIS_ROOT, "ne_10m_admin1/ne_10m_admin_1_states_provinces_lines.shp")
        if not os.path.exists(path):
            self.skipTest(f"缺 {path}")
        hit = sum(1 for r in shpreader.Reader(path).records()
                  if wxplot._is_china(r.attributes, ("adm0_name",)))
        self.assertGreater(hit, 0, "省界命中 0 条")


class FailLoudlyTests(unittest.TestCase):
    """BUG-3：静默失败比报错危险，默认必须炸出来。"""

    def test_raises_when_no_border_drawn(self):
        fig = plt.figure()
        ax = fig.add_subplot(111, projection=ccrs.PlateCarree())
        with self.assertRaises(RuntimeError):
            wxplot.china_map(ax, [105, 125, 20, 42],
                             gis_root="Z:/definitely/not/exist", strict=True)
        plt.close(fig)

    def test_non_strict_warns_but_draws(self):
        fig = plt.figure()
        ax = fig.add_subplot(111, projection=ccrs.PlateCarree())
        wxplot.china_map(ax, [105, 125, 20, 42],
                         gis_root="Z:/definitely/not/exist", strict=False)
        plt.close(fig)

    def test_no_gis_root_does_not_raise(self):
        """不给 gis_root（只画底图）时不应报错。"""
        fig = plt.figure()
        ax = fig.add_subplot(111, projection=ccrs.PlateCarree())
        wxplot.china_map(ax, [105, 125, 20, 42], strict=True)
        plt.close(fig)

    def test_strict_defaults_to_true(self):
        import inspect
        sig = inspect.signature(wxplot.china_map)
        self.assertTrue(sig.parameters["strict"].default,
                        "strict 必须默认开启，否则又回到静默出错")


class LabelOverlapTests(unittest.TestCase):
    """港澳标注过近，需错开。"""

    def test_hk_macao_offsets_exist(self):
        self.assertIn("香港", wxplot.LABEL_OFFSETS)
        self.assertIn("澳门", wxplot.LABEL_OFFSETS)

    def test_offsets_separate_the_labels(self):
        (hx, hy), (mx, my) = wxplot.PROVINCE_XY["香港"], wxplot.PROVINCE_XY["澳门"]
        ohx, ohy = wxplot.LABEL_OFFSETS["香港"]
        omx, omy = wxplot.LABEL_OFFSETS["澳门"]
        dist = ((hx + ohx - mx - omx) ** 2 + (hy + ohy - my - omy) ** 2) ** 0.5
        self.assertGreater(dist, 1.0, "港澳标注仍会重叠")


if __name__ == "__main__":
    unittest.main(verbosity=2)
