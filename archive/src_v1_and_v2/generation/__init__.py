"""Answer generation — Bedrock Claude, prompt management, citations.

Modules:
- prompts: GraphRAG answer prompt templates and builder
- answer_generator: LLM-based answer generation from fused context
"""

from hermes_bedrock_agent.generation.answer_generator import (
    AnswerGenerator,
    AnswerGeneratorConfig,
)
from hermes_bedrock_agent.generation.prompts import (
    build_answer_prompt,
    get_prompt_version,
    get_system_prompt,
)

__all__ = [
    "AnswerGenerator",
    "AnswerGeneratorConfig",
    "build_answer_prompt",
    "get_prompt_version",
    "get_system_prompt",
]
