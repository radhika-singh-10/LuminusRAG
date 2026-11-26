"""LangChain chat model backed by a local MLX-LM model and LoRA adapter."""
# Copyright (c) Lineaje, Inc. All rights reserved.
# Lineaje UnifAI guardrail  version=2.0.0-alpha
def _lineaje_gr_load(_f):
    """Lineaje-added: load gr_stub_client.py beside _f or in one of its 7 parent folders. Missing or broken:
    a pass-through client and ONE warning per process (GR_REQUIRE_CLIENT=1: ImportError instead)."""
    import sys, os, logging, importlib.util as u, pathlib
    n = "_lineaje_gr_stub_client"
    if n in sys.modules: return sys.modules[n]
    h = pathlib.Path(_f or ".").resolve().parent
    d = [h, *h.parents][:8]
    p = next((x / "gr_stub_client.py" for x in d if (x / "gr_stub_client.py").is_file()), None)
    try:
        s = u.spec_from_file_location(n, p) if p else None
        if s is None: raise FileNotFoundError("gr_stub_client.py")
        m = sys.modules[n] = u.module_from_spec(s); s.loader.exec_module(m); return m
    except Exception as e:
        sys.modules.pop(n, None)
        w = ("gr_stub_client.py not found for %s (searched: %s)" % (_f or "<no __file__>", ", ".join(map(str, d)))
             if p is None else "%s failed to load (%s%s)" % (p, type(e).__name__,
                                                          " line %s" % e.lineno if isinstance(e, SyntaxError) else ""))
        w = ("Lineaje guardrail NOT active: " + w + ". Calls pass through unchecked; set GR_REQUIRE_CLIENT=1 to fail "
             "instead. Each deploy unit needs gr_stub_client.py beside its code and GR_SERVICE_URL plus credentials as "
             "environment variables.")
        if os.environ.get("GR_REQUIRE_CLIENT", "").strip() == "1": raise ImportError(w) from (None if p is None else e)
        z = sys.__dict__.setdefault("_lineaje_gr_null", __import__('types').SimpleNamespace(STUB_API=999999, GuardrailUnavailableError=type('GuardrailUnavailableError', (PermissionError,), {}), SiteDescriptor=lambda *a, **k: None, new_interaction_id=lambda *a, **k: None, enforce=lambda _s, _p, *a, **k: _p, enforce_request=lambda _s, _p, *a, **k: _p, enforce_reply=lambda _s, _p, *a, **k: _p, _lineaje_seen=set()))
        k = "missing" if p is None else (str(p), type(e).__name__)
        if k not in z._lineaje_seen:
            z._lineaje_seen.add(k); g = logging.getLogger("lineaje.guardrail"); g.log(30 if p is None else 40, w)
            if g.hasHandlers(): sys.stderr.write(w + "\n")
        return z
__import__("sys").__dict__.setdefault("_lineaje_gr_load_v1", _lineaje_gr_load)
del _lineaje_gr_load
def _lineaje_load_gr_client():
    """Lineaje-added: this file's gr_stub_client.py (the loader _lineaje_gr_load registered)."""
    return __import__("sys").__dict__["_lineaje_gr_load_v1"](globals().get("__file__"))
if __import__("os").environ.get("GR_REQUIRE_CLIENT", "").strip() == "1": __import__("sys").__dict__["_lineaje_gr_load_v1"](globals().get("__file__"))

from functools import lru_cache
from typing import Any, Iterator

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import ConfigDict


@lru_cache(maxsize=2)
def _load_model(model_path: str, adapter_path: str):
    from mlx_lm import load

    return load(model_path, adapter_path=adapter_path)


class MLXChatModel(BaseChatModel):
    """MLX-LM chat model with streaming output for LCEL chains."""

    model_path: str
    adapter_path: str
    temperature: float = 0.0
    max_tokens: int = 512
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "mlx-lm"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model_path": self.model_path, "adapter_path": self.adapter_path}

    def _prompt(self, messages: list[BaseMessage]) -> str:
        _, tokenizer = _load_model(self.model_path, self.adapter_path)
        chat = []
        for message in messages:
            role = getattr(message, "type", "user")
            role = {"human": "user", "ai": "assistant"}.get(role, role)
            # LINEAJE: runtime guardrail checks `role` as it flows from an external API to the agent, after the tool returns (in MLXChatModel._prompt).
            #   Detected: this statement moves data from an external API to the agent with no runtime policy check (detection confidence: medium).
            #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `role` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:3e39f7c57dc4ad4bc061f3f96b35a404a47efb7a826c9e9e738dd72e69baed8b'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:3e39f7c57dc4ad4bc061f3f96b35a404a47efb7a826c9e9e738dd72e69baed8b', phase='post_tool', boundary={'source': 'external_endpoint', 'sink': 'agent_message'}, fail_mode='ALLOW_WITH_AUDIT', source_type='api', destination_type='agent', components={'invocation': {'file': 'rag/mlx_chat.py', 'line': 41, 'function': 'MLXChatModel._prompt'}, 'file': 'rag/mlx_chat.py', 'line': 41, 'function': '_prompt', 'agent_name': 'MLXChatModel', 'agent_name_source': 'inferred_from_class', 'not_on_graph': True})
            try:
                role = _gr_client.enforce(_gr_site, role, content_type='application/json', variable_name='role', source_file=__file__, before_line=41)
            except _gr_client.GuardrailUnavailableError:
                pass
            chat.append({"role": role, "content": str(message.content)})
        return tokenizer.apply_chat_template(
            chat, tokenize=False, add_generation_prompt=True
        )

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        from mlx_lm import stream_generate

        model, tokenizer = _load_model(self.model_path, self.adapter_path)
        prompt = self._prompt(messages)
        max_tokens = int(kwargs.get("max_tokens", self.max_tokens))
        temperature = float(kwargs.get("temperature", self.temperature))
        from mlx_lm.sample_utils import make_sampler

        for response in stream_generate(
            model, tokenizer, prompt, max_tokens=max_tokens,
            sampler=make_sampler(temp=temperature, top_p=0.95 if temperature else 0.0),
        ):
            content = response.text
            if not content:
                continue
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=content))
            if run_manager:
                run_manager.on_llm_new_token(content, chunk=chunk)
            yield chunk

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        chunks = list(self._stream(messages, stop, run_manager, **kwargs))
        message = AIMessage(content="".join(str(c.message.content) for c in chunks))
        return ChatResult(generations=[ChatGeneration(message=message)])
