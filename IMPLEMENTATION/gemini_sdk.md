# IMPLEMENTATION: Gemini Provider (`qa_agent/gemini_provider.py`)

> Google Gemini-specific SDK detail.
> See [`summarise.md`](./summarise.md) for the full command architecture.

---

## Module

`qa_agent/gemini_provider.py`

Implements the standard provider interface (see `qa_agent/providers.py`):

```python
PROVIDER_NAME: str = "Google Gemini"
async def stream(request: ProviderRequest) -> AsyncIterator[str]
```

This module is a **generic Gemini driver** — any command can use it.

---

## Authentication

Two options, checked in order by `_resolve_auth()`:

### 1. Gemini API Key (Google AI Studio)
```bash
export GEMINI_API_KEY=AIza...
# or equivalently:
export GOOGLE_API_KEY=AIza...
```
Get a key at [aistudio.google.com](https://aistudio.google.com).

### 2. Vertex AI + gcloud Application Default Credentials
```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project
export GOOGLE_CLOUD_LOCATION=us-central1   # optional, defaults to "global"
```
`gcloud` must be installed and `GOOGLE_CLOUD_PROJECT` must be set.

### Auth failure message
```
✗ Authentication failed.

  Option 1 — Gemini API key (Google AI Studio):
    export GEMINI_API_KEY=AIza...

  Option 2 — Vertex AI (gcloud ADC):
    gcloud auth application-default login
    export GOOGLE_CLOUD_PROJECT=your-project
    export GOOGLE_CLOUD_LOCATION=us-central1
```

---

## API Details

```python
# API key mode
client = genai.Client(api_key=api_key)

# Vertex AI mode
client = genai.Client(vertexai=True, project=project, location=location)

# Streaming call
client.models.generate_content_stream(
    model=model,            # default: gemini-2.0-flash
    contents=user_prompt,
    config=GenerateContentConfig(
        system_instruction=system_prompt,
        max_output_tokens=4096,
        temperature=0.2,
    ),
)
```

---

## ProviderRequest.extra Keys

| Key | Default | Description |
|-----|---------|-------------|
| `model` | `"gemini-2.0-flash"` | Model to use (e.g. `"gemini-2.5-flash"`, `"gemini-1.5-pro"`) |
| `max_tokens` | `4096` | Max output tokens |
| `temperature` | `0.2` | Sampling temperature |

---

## Error Types Raised

| Exception | Cause |
|-----------|-------|
| `RuntimeError` | Auth failure or SDK not installed |
| `google.api_core.exceptions.PermissionDenied` | Invalid credentials or project |
| `google.api_core.exceptions.ResourceExhausted` | Quota exceeded |

---

## Status

| Field | Value |
|-------|-------|
| Status | ✅ Active |
| SDK | `google-genai` |
| Install | `pip install google-genai` |
