"""元数据与目录结构测试。

把仓库的"形状"也纳入测试：插件元数据、评测集、skill 路径、许可证。
这些一旦被误改（比如手滑删掉 LICENSE、把 skill 移回旧位置），
CI 就会直接失败，而不是等到用户安装时才发现。
"""
from __future__ import annotations
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / ".claude-plugin"
SKILL_DIR = ROOT / "skills" / "era5-wrf-pipeline"
EVALS = ROOT / "evals" / "era5-wrf-pipeline" / "evals.json"


class RepositoryLayoutTests(unittest.TestCase):
    def test_skill_at_standard_path(self):
        """插件规范要求 skill 位于 skills/<name>/SKILL.md。"""
        self.assertTrue((SKILL_DIR / "SKILL.md").is_file(),
                        "SKILL.md 不在 skills/era5-wrf-pipeline/ 下")

    def test_license_present(self):
        self.assertTrue((ROOT / "LICENSE").is_file(), "缺少 LICENSE")

    def test_license_is_mit(self):
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", text)

    def test_plugin_metadata_keys(self):
        data = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        for key in ("name", "version", "description", "license", "repository"):
            self.assertIn(key, data)
        self.assertEqual(data["license"], "MIT")

    def test_marketplace_lists_this_plugin(self):
        data = json.loads((PLUGIN / "marketplace.json").read_text(encoding="utf-8"))
        names = [p["name"] for p in data["plugins"]]
        self.assertIn("era5-wrf-pipeline", names)
        for plugin in data["plugins"]:
            self.assertIn("source", plugin)

    def test_plugin_version_matches_marketplace(self):
        plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        market = json.loads((PLUGIN / "marketplace.json").read_text(encoding="utf-8"))
        listed = {p["name"]: p.get("version") for p in market["plugins"]}
        self.assertEqual(listed.get(plugin["name"]), plugin["version"],
                         "plugin.json 与 marketplace.json 版本号不一致")

    def test_readme_mentions_current_version(self):
        """README 必须提到当前插件版本，避免文档与元数据脱节。"""
        import re
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        versions = set(re.findall(r"v(\d+\.\d+\.\d+)", readme))
        self.assertIn(plugin["version"], versions,
                      f"README 未提及当前版本 v{plugin['version']}")

    def test_readme_license_matches_license_file(self):
        """README 的许可表述必须与实际 LICENSE 文件一致。

        这类矛盾不会报错、不会影响运行，只会静默误导使用者：
        例如 LICENSE 已存在，README 却说「尚未选定 LICENSE」。
        """
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertTrue((ROOT / "LICENSE").is_file())
        self.assertIn("MIT", readme, "LICENSE 是 MIT，但 README 未提及")

        # 不得再声称尚未选定许可证
        for stale in ("尚未选定 LICENSE", "没有许可证", "无 LICENSE"):
            self.assertNotIn(
                stale, readme,
                f"README 仍含过时表述「{stale}」，而 LICENSE 文件已存在")

    def test_readme_points_to_license_file(self):
        """README 应链接到 LICENSE 文件，方便使用者查看条款。"""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("](LICENSE)", readme, "README 未链接 LICENSE 文件")

    def test_no_stale_license_claim_in_skill(self):
        """SKILL.md 也不得声称无许可证。"""
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        for stale in ("尚未选定 LICENSE", "没有许可证"):
            self.assertNotIn(stale, text, f"SKILL.md 含过时表述「{stale}」")


class EvalsTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(EVALS.read_text(encoding="utf-8"))

    def test_evals_exist_and_are_substantive(self):
        items = self.data.get("evals", [])
        self.assertGreaterEqual(len(items), 5, "评测场景不应少于 5 条")

    def test_each_eval_has_required_fields(self):
        required = {"id", "prompt", "expected_output"}
        for item in self.data["evals"]:
            self.assertTrue(
                required.issubset(set(item)),
                f"场景缺少字段: {item.get('id')}")
            self.assertTrue(str(item["prompt"]).strip())
            self.assertTrue(str(item["expected_output"]).strip())

    def test_eval_ids_unique(self):
        ids = [item["id"] for item in self.data["evals"]]
        self.assertEqual(len(ids), len(set(ids)), "评测 id 重复")


class SkillContentTests(unittest.TestCase):
    """确保关键知识没有在后续编辑中被删掉。"""

    def setUp(self):
        self.text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    def test_sst_pitfall_documented(self):
        self.assertIn("era5-input-pitfalls.md", self.text,
                      "SKILL.md 未引用 ERA5 输入陷阱文档")
        pitfall = SKILL_DIR / "references" / "era5-input-pitfalls.md"
        self.assertTrue(pitfall.is_file())
        body = pitfall.read_text(encoding="utf-8")
        for token in ("SST", "0 K", "SKINTEMP", "LANDSEA"):
            self.assertIn(token, body, f"陷阱文档缺少关键内容: {token}")

    def test_border_field_names_documented(self):
        for token in ("ADM0_LEFT", "ADM0_NAME"):
            self.assertIn(token, self.text,
                          f"SKILL.md 未说明边界字段差异: {token}")

    def test_retry_discipline_kept(self):
        """A/B/C 分类与重试上限是核心差异点，不能被删。"""
        for token in ("A 参数级", "B 资源/环境级", "C 科学设计级", "最多 3 次"):
            self.assertIn(token, self.text, f"重试纪律内容缺失: {token}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
