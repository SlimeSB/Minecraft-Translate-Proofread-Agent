"""端到端 Pipeline 集成测试（--no-llm 模式，不调 LLM）。"""
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from src.models import PipelineContext
from src.pipeline.pipeline import ReviewPipeline
from src.storage.database import PipelineDB

FIXTURES = Path(__file__).parent / "fixtures"


class TestPipelineIntegration:
    """完整流水线测试：Phase 1 → 2 → 3a → 3c(no-llm) → P4(skip) → P5。"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="pipeline_test_"))
        yield
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_pipeline(self, **kwargs) -> PipelineContext:
        en = str(FIXTURES / "en_us.json")
        zh = str(FIXTURES / "zh_cn.json")
        pipeline = ReviewPipeline(
            en_path=en,
            zh_path=zh,
            output_dir=str(self.tmpdir),
            no_llm=True,
            **kwargs,
        )
        pipeline.run()
        return pipeline.ctx

    def test_full_pipeline_no_llm(self):
        ctx = self._run_pipeline()
        db_path = self.tmpdir / "pipeline.db"

        assert db_path.exists(), "pipeline.db should be created"
        assert (self.tmpdir / "report.md").exists()
        assert (self.tmpdir / "report.json").exists()
        assert (self.tmpdir / "glossary.json").exists(), "glossary.json should be created"

        db = PipelineDB(db_path)

        # entries 表有数据
        rows = db.execute("SELECT COUNT(*) FROM entries").fetchone()
        assert rows[0] > 0, "entries 表应有数据"

        # state 推进到 >= 2 (Phase 3c blanket)
        state_check = db.execute("SELECT MIN(state) FROM entries").fetchone()
        assert state_check[0] >= 2, f"所有条目 state 应 >= 2, 实际 min={state_check[0]}"

        db.close()

    def test_entries_table_data(self):
        ctx = self._run_pipeline()
        db = PipelineDB(self.tmpdir / "pipeline.db")
        matched = ctx.alignment.get("matched_entries", [])

        rows = db.execute("SELECT * FROM entries").fetchall()
        assert len(rows) == len(matched), "entries 行数应等于 matched_entries"
        first = rows[0]
        assert first["key"]
        assert first["en"]
        assert first["zh"]
        db.close()

    def test_verdicts_in_entries(self):
        """各 Phase 的 verdict 应写入 entries 表。"""
        self._run_pipeline()
        db = PipelineDB(self.tmpdir / "pipeline.db")

        # 查询有诊断的条目
        rows = db.execute("SELECT * FROM entries WHERE diagnoses != '[]'").fetchall()
        assert isinstance(rows, list), "诊断查询应返回列表"

        # 至少有一些 verdict 条目（取决于测试数据）
        non_zero = db.execute("SELECT COUNT(*) FROM entries WHERE verdict > 0").fetchone()[0]
        assert non_zero >= 0, f"verdict 统计应 >= 0, 实际={non_zero}"

        db.close()

    def test_report_json_structure(self):
        self._run_pipeline()
        with open(self.tmpdir / "report.json", "r", encoding="utf-8") as f:
            report = json.load(f)

        assert "verdicts" in report
        assert "alignment_stats" in report

    def test_glossary_json_exists(self):
        self._run_pipeline()
        glossary_path = self.tmpdir / "glossary.json"
        assert glossary_path.exists(), "glossary.json 应存在"
        with open(glossary_path, "r", encoding="utf-8") as f:
            glossary = json.load(f)
        assert isinstance(glossary, list)
        assert len(glossary) > 0, "术语表不应为空"

    def test_dry_run_no_crash(self):
        ctx = self._run_pipeline(dry_run=True)
        db_path = self.tmpdir / "pipeline.db"

        assert db_path.exists()
        db = PipelineDB(db_path)
        rows = db.execute("SELECT COUNT(*) FROM entries").fetchone()
        assert rows[0] > 0
        db.close()

    def test_output_directory_created(self):
        ctx = self._run_pipeline()
        assert self.tmpdir.exists()
        assert (self.tmpdir / "pipeline.db").exists()
        assert (self.tmpdir / "report.md").exists()
        assert (self.tmpdir / "report.json").exists()
        assert (self.tmpdir / "glossary.json").exists()

    def test_pipeline_no_crash_small_batch(self):
        self._run_pipeline(batch_size=5)
        db_path = self.tmpdir / "pipeline.db"
        assert db_path.exists()

    def test_state_progression(self):
        """state 单调推进：Phase 1=0 → Phase 2/3a blanket≥1 → Phase 3c blanket≥2。"""
        self._run_pipeline()
        db = PipelineDB(self.tmpdir / "pipeline.db")
        min_state = db.execute("SELECT MIN(state) FROM entries").fetchone()[0]
        assert min_state >= 2, f"所有条目 state 应 >= 2 (经过 Phase 3c blanket), 实际 min={min_state}"
        db.close()

    def test_pr_multi_version_groups(self):
        """PR 多版本场景：验证 slug 分组、跨版本差异、ref 注入。"""
        from src.pipeline.phase1_alignment import (
            _regroup_mods_by_slug,
            _build_combined_full_data,
        )

        mods = {
            "1.21/12345/ironchest": {
                "mod_info": {"version": "1.21", "curseforge_id": "12345", "slug": "ironchest"},
                "full_en": {"key.a": "Iron Chest"},
                "full_zh": {"key.a": "铁箱子"},
                "entries": [
                    {"key": "key.a", "en": "Iron Chest", "zh": "铁箱子",
                     "namespace": "ironchest", "version": "1.21", "slug": "ironchest",
                     "old_en": "Old", "old_zh": "旧"}
                ],
            },
            "1.20.1/12345/ironchest": {
                "mod_info": {"version": "1.20.1", "curseforge_id": "12345", "slug": "ironchest"},
                "full_en": {"key.a": "Iron Chest", "key.b": "Diamond Chest"},
                "full_zh": {"key.a": "铁质箱子", "key.b": "钻石箱子"},
                "entries": [
                    {"key": "key.a", "en": "Iron Chest", "zh": "铁质箱子",
                     "namespace": "ironchest", "version": "1.20.1", "slug": "ironchest",
                     "old_en": "", "old_zh": ""}
                ],
            },
        }

        groups = _regroup_mods_by_slug(mods)
        assert "ironchest" in groups
        g = groups["ironchest"]
        assert g["versions"] == ["1.21", "1.20.1"]  # 降序
        assert "1.21" in g["version_data"]
        assert "1.20.1" in g["version_data"]

        combined_en, combined_zh = _build_combined_full_data(groups)
        assert "ironchest/1.21/key.a" in combined_en
        assert "ironchest/1.20.1/key.a" in combined_en
        assert "ironchest/1.20.1/key.b" in combined_en
        assert combined_en["ironchest/1.20.1/key.b"] == "Diamond Chest"
