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
    """完整流水线测试：Phase 1 → 2 → 3a → 3c(no-llm) → Merge → P4(skip) → P5。"""

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

        db = PipelineDB(db_path)

        alignment = db.load_alignment()
        assert len(alignment) > 0

        glossary = db.load_glossary()
        assert len(glossary) > 0, "术语表不应为空"

        all_verdicts = db.load_verdicts(phase="merged")
        assert len(all_verdicts) > 0

        stats_raw = db.get_meta("stats")
        assert stats_raw is not None
        stats = json.loads(stats_raw)
        assert isinstance(stats, dict)

        db.close()

    def test_alignment_table_data(self):
        ctx = self._run_pipeline()
        db = PipelineDB(self.tmpdir / "pipeline.db")
        alignment = db.load_alignment()
        matched = ctx.alignment.get("matched_entries", [])
        db.close()

        assert len(alignment["matched_entries"]) == len(matched)
        first = alignment["matched_entries"][0]
        assert first["key"]
        assert first["en"]
        assert first["zh"]

    def test_verdicts_by_phase(self):
        self._run_pipeline()
        db = PipelineDB(self.tmpdir / "pipeline.db")

        for phase in ("format", "terminology", "merged"):
            v = db.load_verdicts(phase=phase)
            assert isinstance(v, list), f"verdicts({phase}) should be a list"

        db.close()

    def test_report_json_structure(self):
        self._run_pipeline()
        with open(self.tmpdir / "report.json", "r", encoding="utf-8") as f:
            report = json.load(f)

        assert "verdicts" in report
        assert "alignment_stats" in report
        assert "by_namespace" in report

    def test_dry_run_no_crash(self):
        ctx = self._run_pipeline(dry_run=True)
        db_path = self.tmpdir / "pipeline.db"

        assert db_path.exists()
        db = PipelineDB(db_path)
        assert len(db.load_alignment()) > 0
        db.close()

    def test_output_directory_created(self):
        ctx = self._run_pipeline()
        assert self.tmpdir.exists()
        assert (self.tmpdir / "pipeline.db").exists()
        assert (self.tmpdir / "report.md").exists()
        assert (self.tmpdir / "report.json").exists()

    def test_pipeline_no_crash_small_batch(self):
        self._run_pipeline(batch_size=5)
        db_path = self.tmpdir / "pipeline.db"
        assert db_path.exists()

    def test_meta_stats_present(self):
        self._run_pipeline()
        db = PipelineDB(self.tmpdir / "pipeline.db")
        stats_raw = db.get_meta("stats")
        assert stats_raw is not None
        stats = json.loads(stats_raw)
        for key in ("PASS",):
            assert key in stats, f"stats missing '{key}'"
        db.close()

    def test_format_verdicts_produced(self):
        ctx = self._run_pipeline()
        assert isinstance(ctx.format_verdicts, list)
        assert len(ctx.format_verdicts) > 0, "format check should produce verdicts"

    def test_term_verdicts_produced(self):
        ctx = self._run_pipeline()
        assert isinstance(ctx.term_verdicts, list)
