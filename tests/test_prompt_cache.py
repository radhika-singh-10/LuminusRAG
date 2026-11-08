"""Prompt caching only works if every system prompt is byte-identical across
requests: no template variables in the system message. Run: python tests/test_prompt_cache.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.prompts import SystemMessagePromptTemplate  # noqa: E402

from rag.prompt_cache import system_prompts  # noqa: E402


def test_system_prompts_are_static():
    for name, (_, prompt, sample) in system_prompts().items():
        system = prompt.messages[0]
        assert isinstance(system, SystemMessagePromptTemplate), name
        assert system.prompt.input_variables == [], f"{name}: system prompt has variables"
        # Same system text for different inputs -> same cacheable prefix.
        other = {k: "something else entirely" for k in sample}
        assert prompt.invoke(sample).to_messages()[0].content == \
            prompt.invoke(other).to_messages()[0].content, name


def test_all_ollama_calls_use_keep_alive_factory():
    root = Path(__file__).resolve().parent.parent / "rag"
    offenders = [str(p) for p in root.rglob("*.py")
                 if "ChatOllama(" in p.read_text() and p.name != "prompt_cache.py"]
    assert not offenders, f"create Ollama models with prompt_cache.chat_ollama: {offenders}"


if __name__ == "__main__":
    for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith("test_")):
        fn()
        print(f"PASS {name}")
