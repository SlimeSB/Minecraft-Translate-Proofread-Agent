"""向后兼容重导出 —— 请改用 src.pipeline.pipeline.ReviewPipeline。"""
from src.pipeline.pipeline import ReviewPipeline

__all__ = ["ReviewPipeline"]
