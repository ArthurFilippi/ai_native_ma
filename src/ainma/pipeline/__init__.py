"""Linear async question answering pipeline: understand, retrieve, write, verify, contradictions,
abstain. Entry point: `ask`."""

from ainma.pipeline.ask import AskOutcome, ask, ask_detailed
from ainma.pipeline.config import PipelineConfig

__all__ = ["AskOutcome", "PipelineConfig", "ask", "ask_detailed"]
