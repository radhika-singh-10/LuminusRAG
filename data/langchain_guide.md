# LangChain Quick Guide

A practical overview of LangChain (Python) covering setup, core concepts, and common patterns. APIs evolve quickly, so confirm details against the official docs: https://docs.langchain.com

---

## 1. What is LangChain?

LangChain is an open-source framework for building applications powered by large language models (LLMs). It provides:

- **Model integrations**: a common interface to OpenAI, Anthropic, Google, Ollama, and many others
- **Prompts and output parsing**: reusable templates and structured outputs
- **Tools**: let models call functions and external APIs
- **Agents**: models that decide which tools to use in a loop
- **Retrieval (RAG)**: connect models to your own documents
- **LangGraph**: the lower-level orchestration runtime that LangChain agents are built on (state, branching, persistence, human-in-the-loop)
- **LangSmith**: tracing, evaluation, and monitoring

---

## 2. Installation

```bash
pip install -U langchain

# Provider packages (install what you need)
pip install -U langchain-anthropic
pip install -U langchain-openai
pip install -U langchain-google-genai

# Optional extras
pip install -U langchain-community langgraph langchain-text-splitters
```

Set API keys as environment variables:

```bash
export ANTHROPIC_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
```

---

## 3. Chat Models

### Provider-agnostic initialization

```python
from langchain.chat_models import init_chat_model

model = init_chat_model("anthropic:claude-sonnet-4-5")
# model = init_chat_model("openai:gpt-4o")

response = model.invoke("Explain vector databases in one sentence.")
print(response.content)
```

### Provider-specific classes

```python
from langchain_anthropic import ChatAnthropic

model = ChatAnthropic(model="claude-sonnet-4-5", temperature=0)
```

### Messages

```python
from langchain_core.messages import SystemMessage, HumanMessage

messages = [
    SystemMessage("You are a concise technical assistant."),
    HumanMessage("What is an embedding?"),
]
print(model.invoke(messages).content)
```

### Streaming and batching

```python
for chunk in model.stream("Write a haiku about Python."):
    print(chunk.content, end="", flush=True)

results = model.batch(["Define RAG.", "Define LCEL."])
```

Async versions: `ainvoke`, `astream`, `abatch`.

---

## 4. Prompt Templates

```python
from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful assistant that translates to {language}."),
    ("human", "{text}"),
])

chain = prompt | model
print(chain.invoke({"language": "French", "text": "Good morning"}).content)
```

---

## 5. LCEL (LangChain Expression Language)

The `|` operator composes components ("Runnables") into pipelines. Every Runnable supports `invoke`, `stream`, `batch`, and async variants.

```python
from langchain_core.output_parsers import StrOutputParser

chain = prompt | model | StrOutputParser()
print(chain.invoke({"language": "Spanish", "text": "Thank you"}))
```

### Parallel and passthrough

```python
from langchain_core.runnables import RunnableParallel, RunnablePassthrough

parallel = RunnableParallel(
    summary=prompt_a | model | StrOutputParser(),
    keywords=prompt_b | model | StrOutputParser(),
)

chain = {"question": RunnablePassthrough()} | prompt | model
```

### Custom functions

```python
from langchain_core.runnables import RunnableLambda

shout = RunnableLambda(lambda s: s.upper())
chain = prompt | model | StrOutputParser() | shout
```

---

## 6. Structured Output

Get validated, typed data back from the model.

```python
from pydantic import BaseModel, Field

class Person(BaseModel):
    name: str = Field(description="Full name")
    age: int = Field(description="Age in years")

structured_model = model.with_structured_output(Person)
person = structured_model.invoke("Alice is 30 years old.")
print(person.name, person.age)
```

---

## 7. Tools

Tools are functions the model can request to call.

```python
from langchain_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"It is sunny in {city}."

model_with_tools = model.bind_tools([get_weather])
response = model_with_tools.invoke("What's the weather in Paris?")
print(response.tool_calls)
```

Tips:
- The **docstring** becomes the tool description the model sees, so write it clearly.
- Use type hints; they define the tool's input schema.

---

## 8. Agents

An agent runs a loop: the model reasons, calls tools, observes results, and repeats until it can answer.

```python
from langchain.agents import create_agent

agent = create_agent(
    model="anthropic:claude-sonnet-4-5",
    tools=[get_weather],
    system_prompt="You are a helpful assistant.",
)

result = agent.invoke(
    {"messages": [{"role": "user", "content": "What's the weather in Tokyo?"}]}
)
print(result["messages"][-1].content)
```

Agents are built on LangGraph, so you get streaming, persistence, and human-in-the-loop support when you need them. For fully custom control flow, build directly with LangGraph.

### Memory (conversation persistence)

```python
from langgraph.checkpoint.memory import InMemorySaver

agent = create_agent(
    model="anthropic:claude-sonnet-4-5",
    tools=[get_weather],
    checkpointer=InMemorySaver(),
)

config = {"configurable": {"thread_id": "user-1"}}
agent.invoke({"messages": [{"role": "user", "content": "My name is Sam."}]}, config)
agent.invoke({"messages": [{"role": "user", "content": "What's my name?"}]}, config)
```

Use a database-backed checkpointer (e.g. Postgres) in production.

---

## 9. Retrieval-Augmented Generation (RAG)

### Pipeline overview

1. **Load** documents
2. **Split** into chunks
3. **Embed** and store in a vector store
4. **Retrieve** relevant chunks at query time
5. **Generate** an answer using the retrieved context

### Example

```python
from langchain_community.document_loaders import WebBaseLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_core.vectorstores import InMemoryVectorStore

# 1. Load
docs = WebBaseLoader("https://example.com/article").load()

# 2. Split
splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
chunks = splitter.split_documents(docs)

# 3. Embed + store
vector_store = InMemoryVectorStore(OpenAIEmbeddings())
vector_store.add_documents(chunks)

# 4. Retrieve
retriever = vector_store.as_retriever(search_kwargs={"k": 4})

# 5. Generate
rag_prompt = ChatPromptTemplate.from_messages([
    ("system", "Answer using only this context:\n\n{context}"),
    ("human", "{question}"),
])

def format_docs(docs):
    return "\n\n".join(d.page_content for d in docs)

rag_chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | rag_prompt
    | model
    | StrOutputParser()
)

print(rag_chain.invoke("What is the main point of the article?"))
```

### Common vector stores

Chroma, FAISS, Pinecone, Weaviate, Qdrant, pgvector, and more. All share the same `add_documents` / `as_retriever` interface.

### Retrieval as an agent tool

Wrap the retriever in a `@tool` so an agent can decide when to search:

```python
@tool
def search_docs(query: str) -> str:
    """Search the knowledge base for relevant information."""
    return format_docs(retriever.invoke(query))
```

---

## 10. Observability with LangSmith

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY="your-key"
export LANGSMITH_PROJECT="my-project"
```

With these set, every chain and agent run is traced automatically, so you can inspect prompts, tool calls, latency, and token usage.

---

## 11. Best Practices

- **Start simple**: a prompt plus a model is often enough. Add agents only when you need dynamic tool use.
- **Use structured output** instead of parsing free text.
- **Write good tool descriptions**; the model picks tools based on them.
- **Tune chunking** in RAG (size, overlap) and evaluate retrieval quality separately from generation.
- **Add tracing early** (LangSmith) to debug behavior.
- **Set timeouts, retries, and token limits** for production reliability.
- **Keep secrets in environment variables**, never in code.
- **Pin versions** in `requirements.txt`; the ecosystem moves fast.

---

## 12. Cheat Sheet

| Task | Code |
|------|------|
| Init any model | `init_chat_model("provider:model")` |
| Call a model | `model.invoke(...)` |
| Stream | `model.stream(...)` |
| Prompt template | `ChatPromptTemplate.from_messages([...])` |
| Chain | `prompt \| model \| StrOutputParser()` |
| Structured output | `model.with_structured_output(Schema)` |
| Define tool | `@tool` decorator |
| Bind tools | `model.bind_tools([...])` |
| Create agent | `create_agent(model=..., tools=[...])` |
| Add memory | `checkpointer=InMemorySaver()` |
| Split text | `RecursiveCharacterTextSplitter` |
| Retriever | `vector_store.as_retriever()` |

---

## 13. Resources

- Docs: https://docs.langchain.com
- Python API reference: https://reference.langchain.com
- LangGraph: https://langchain-ai.github.io/langgraph/
- LangSmith: https://smith.langchain.com
- GitHub: https://github.com/langchain-ai/langchain
