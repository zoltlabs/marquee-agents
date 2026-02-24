# IMPLEMENTATION: OpenAI Provider (`qa_agent/openai_provider.py`)

> OpenAI-specific SDK detail.
> See [`summarise.md`](./summarise.md) for the full command architecture.

---

## Module

`qa_agent/openai_provider.py`

Implements the standard provider interface (see `qa_agent/providers.py`):

```python
PROVIDER_NAME: str = "OpenAI (GPT)"
async def stream(request: ProviderRequest) -> AsyncIterator[str]
```

This module is a **generic OpenAI driver** — any command can use it.

---

## Note on Codex SDK

The official Codex SDK (`@openai/codex-sdk`) is TypeScript-only.
This module uses the official **`openai` Python package** targeting the
Chat Completions API with streaming — the same model family (GPT-4o, o3, etc.)
that powers Codex agents — giving full Python-native access.

---

## Authentication

Checked in order by `_resolve_auth()`:

### 1. API Key
```bash
export OPENAI_API_KEY=sk-...
```

### 2. Codex CLI OAuth
```bash
npm install -g @openai/codex
codex login
```
After `codex login`, credentials are stored at `~/.codex/auth.json`.
The provider reads the `apiKey` field from that file.

### Auth failure message
```
✗ Authentication failed.

  Option 1 — API key:
    export OPENAI_API_KEY=sk-...

  Option 2 — Codex CLI OAuth:
    npm install -g @openai/codex
    codex login
```

---

## API Details

```python
client.chat.completions.create(
    model=model,           # default: gpt-4o
    messages=[
        {"role": "system", "content": system_prompt + "\nWorking directory: ..."},
        {"role": "user",   "content": user_prompt},
    ],
    stream=True,
    max_completion_tokens=4096,
)
```

---

## ProviderRequest.extra Keys

| Key | Default | Description |
|-----|---------|-------------|
| `model` | `"gpt-4o"` | Model to use (e.g. `"o3"`, `"gpt-4o-mini"`) |
| `max_tokens` | `4096` | Max completion tokens |

---

## Error Types Raised

| Exception | Cause |
|-----------|-------|
| `RuntimeError` | Auth failure or SDK not installed |
| `openai.AuthenticationError` | Invalid API key |
| `openai.RateLimitError` | Rate limit hit |

---

## Status

| Field | Value |
|-------|-------|
| Status | ✅ Active |
| SDK | `openai` |
| Install | `pip install openai` |
