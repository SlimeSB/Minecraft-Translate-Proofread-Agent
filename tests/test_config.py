"""测试全局配置模块。"""
import unittest
from unittest.mock import patch

from src.config import _flatten, _as_text


class TestFlatten(unittest.TestCase):

    def test_empty_config_defaults(self):
        flat = _flatten({})
        self.assertEqual(flat["max_workers"], 4)
        self.assertEqual(flat["filter_batch_size"], 50)
        self.assertEqual(flat["term_min_freq"], 5)
        self.assertEqual(flat["term_min_consensus"], 0.6)
        self.assertEqual(flat["term_max_zh_len"], 40)
        self.assertEqual(flat["term_max_en_len"], 60)
        self.assertEqual(flat["term_consensus_min_total"], 3)
        self.assertEqual(flat["fuzzy_cluster_threshold"], 65.0)
        self.assertEqual(flat["fuzzy_cluster_top_n"], 200)
        self.assertEqual(flat["default_pr_repo"], "CFPAOrg/Minecraft-Mod-Language-Package")
        self.assertEqual(flat["desc_key_suffixes"], [])
        self.assertEqual(flat["punctuation_spacing_whitelist"], [])
        self.assertEqual(flat["term_blacklist"], [])

    def test_pipeline_group(self):
        flat = _flatten({"pipeline": {"max_workers": 8, "filter_batch_size": 100}})
        self.assertEqual(flat["max_workers"], 8)
        self.assertEqual(flat["filter_batch_size"], 100)

    def test_terminology_group(self):
        flat = _flatten({"terminology": {
            "min_freq": 3, "min_consensus": 0.8, "max_zh_len": 60,
            "max_en_len": 80, "consensus_min_total": 5,
            "fuzzy_cluster_threshold": 70.0, "fuzzy_cluster_top_n": 150,
            "blacklist": ["foo", "bar"]
        }})
        self.assertEqual(flat["term_min_freq"], 3)
        self.assertEqual(flat["term_min_consensus"], 0.8)
        self.assertEqual(flat["term_max_zh_len"], 60)
        self.assertEqual(flat["term_max_en_len"], 80)
        self.assertEqual(flat["term_consensus_min_total"], 5)
        self.assertEqual(flat["fuzzy_cluster_threshold"], 70.0)
        self.assertEqual(flat["fuzzy_cluster_top_n"], 150)
        self.assertEqual(flat["term_blacklist"], ["foo", "bar"])

    def test_llm_group(self):
        flat = _flatten({"llm": {
            "system_prompt": "You are a translator",
            "header_prefix": "Review:",
            "default_review_focus": "accuracy",
            "review_instruction": ["Check 1", "Check 2"],
            "review_principles": ["Be concise"],
            "merge_system_prompt": ["Merge these"],
            "keyboard_guidance": "keyboard tips",
            "mouse_guidance": "mouse tips",
            "filter": {
                "system_prompt": "Filter prompt",
                "instruction": ["Filter instruction"]
            }
        }})
        self.assertEqual(flat["review_system_prompt"], "You are a translator")
        self.assertEqual(flat["review_header_prefix"], "Review:")
        self.assertEqual(flat["default_review_focus"], "accuracy")
        self.assertEqual(flat["review_instruction"], ["Check 1", "Check 2"])
        self.assertEqual(flat["review_principles"], ["Be concise"])
        self.assertEqual(flat["filter_system_prompt"], "Filter prompt")
        self.assertEqual(flat["filter_instruction"], ["Filter instruction"])

    def test_key_prefixes_llm_required(self):
        flat = _flatten({"key_prefixes": {
            "death.": {"llm_required": True},
            "item.": {"llm_required": False},
            "block.": {},
        }})
        self.assertEqual(flat["llm_required_prefixes"], ["death."])

    def test_format_group(self):
        flat = _flatten({"format": {
            "desc_key_suffixes": [".desc", ".lore"],
            "punctuation_spacing_whitelist": ["book.", "patchouli."]
        }})
        self.assertEqual(flat["desc_key_suffixes"], [".desc", ".lore"])
        self.assertEqual(flat["punctuation_spacing_whitelist"], ["book.", "patchouli."])

    def test_pr_group(self):
        flat = _flatten({"pr": {
            "change_context_prompt": "Context goes here",
            "default_repo": "MyOrg/MyRepo"
        }})
        self.assertEqual(flat["pr_change_context_prompt"], "Context goes here")
        self.assertEqual(flat["default_pr_repo"], "MyOrg/MyRepo")

    def test_partial_overrides(self):
        flat = _flatten({"pipeline": {"max_workers": 2}, "terminology": {"min_freq": 2}})
        self.assertEqual(flat["max_workers"], 2)
        self.assertEqual(flat["filter_batch_size"], 50)
        self.assertEqual(flat["term_min_freq"], 2)
        self.assertEqual(flat["term_min_consensus"], 0.6)


class TestAsText(unittest.TestCase):

    def test_string_passthrough(self):
        self.assertEqual(_as_text("hello"), "hello")

    def test_list_joined(self):
        self.assertEqual(_as_text(["line1", "line2"]), "line1\nline2")

    def test_single_item_list(self):
        self.assertEqual(_as_text(["only"]), "only")

    def test_empty_list(self):
        self.assertEqual(_as_text([]), "")


class TestGetWithMock(unittest.TestCase):

    @patch("src.config._cfg_cache", None)
    def test_get_with_mock_file(self):
        import json
        import builtins
        config_json = json.dumps({
            "pipeline": {"max_workers": 10},
            "terminology": {"min_freq": 3}
        })
        mock_open = unittest.mock.mock_open(read_data=config_json)
        with patch("builtins.open", mock_open):
            from src.config import _cfg_cache as cache_module
            import src.config as cfg
            cfg._cfg_cache = None
            self.assertEqual(cfg.get("max_workers", 4), 10)
            self.assertEqual(cfg.get("term_min_freq", 5), 3)
            self.assertEqual(cfg.get("nonexistent", 99), 99)

    @patch("src.config._cfg_cache", None)
    def test_get_file_not_found_uses_defaults(self):
        mock_open = unittest.mock.mock_open()
        mock_open.side_effect = FileNotFoundError
        with patch("builtins.open", mock_open):
            import src.config as cfg
            cfg._cfg_cache = None
            self.assertEqual(cfg.get("max_workers", 4), 4)
            self.assertEqual(cfg.get("filter_batch_size", 50), 50)


if __name__ == "__main__":
    unittest.main()
