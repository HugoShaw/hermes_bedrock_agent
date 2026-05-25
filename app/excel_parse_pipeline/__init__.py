"""Excel Parse Pipeline - AI-driven parse plan generation and execution for enterprise Excel workbooks."""

from .config import PipelineConfig
from .pipeline import run_pipeline

__version__ = "1.0.0"
__all__ = ["PipelineConfig", "run_pipeline"]
