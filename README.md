## Avoiding the "Event loop is closed" pitfall

### What happens 🤔

When you call `asyncio.run()` **more than once** in the same process:

1. Python spins up a new event‑loop, executes your coroutine, **then closes the loop**.
2. Async SDKs (OpenAI, Gemini, Anthropic, …) create `httpx.AsyncClient` objects for every request. They attempt to close their TLS sockets *after* your loop is gone.
3. On shutdown the SDK calls `await client.aclose()`, but the loop that created the sockets is already closed →

   ```text
   RuntimeError: Event loop is closed
   ```

   * OpenAI’s library quietly retries, so you just see “Retrying …”.
   * Gemini and some others surface the error and the second call fails.

### One‑line fix ✅

Keep **one event‑loop alive** for the whole process and run every coroutine inside it:

```python
from async_tools import run_sync  # 👈 helper

links = run_sync(scrape_and_extract_async(url, links_cfg))
```

---

### `async_tools.py` (drop‑in utility)

```python
import asyncio, threading, atexit, functools
from typing import Awaitable, TypeVar, Callable

T = TypeVar("T")
_LOOP: asyncio.AbstractEventLoop | None = None

def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _LOOP
    if _LOOP is None:
        _LOOP = asyncio.new_event_loop()
        threading.Thread(
            target=_LOOP.run_forever,
            daemon=True,
            name="persistent-event-loop",
        ).start()
        atexit.register(lambda: _LOOP.call_soon_threadsafe(_LOOP.stop))
    return _LOOP

def run_sync(coro: Awaitable[T]) -> T:
    """Run *coro* in the persistent loop, blocking until it finishes."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():          # Jupyter / FastAPI / etc.
        return coro                         # caller must `await`

    future = asyncio.run_coroutine_threadsafe(coro, _ensure_loop())
    return future.result()

def to_sync(fn: Callable[..., Awaitable[T]]) -> Callable[..., T]:
    """Decorator: expose an async function as sync."""
    return functools.wraps(fn)(lambda *a, **kw: run_sync(fn(*a, **kw)))
```

---

### How to use

                                                        
**Block until coroutine finishes**    
```                          
links = run_sync(scrape_and_extract_async(url, links_cfg))
```

**Convert an async helper to a sync API**
```
@to_sync
async def get_questions(ctx):
    return await llm_extract_async(ctx, questions_cfg)

qs = get_questions(context)
``` 

**Prefer full async when you can**
```
async def main():
    links = await scrape_and_extract_async(url, links_cfg)
    qs    = await llm_extract_async(context, questions_cfg)

if __name__ == "__main__":
    asyncio.run(main())   # called exactly once
```

Either approach guarantees **no more `RuntimeError: Event loop is closed`**, regardless of which LLM provider you plug in.
