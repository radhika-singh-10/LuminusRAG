"""LangChain chat model backed by a local MLX-LM model and LoRA adapter."""
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
