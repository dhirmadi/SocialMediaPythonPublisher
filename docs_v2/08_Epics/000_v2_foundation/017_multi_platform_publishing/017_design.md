<!-- docs_v2/08_Epics/08_02_Feature_Design/017_multi-platform-publishing_design.md -->

# Design: Multi-Platform Publishing Engine

## 1. Summary
The Publishing Engine enables parallel distribution of content to multiple social media platforms using a unified plugin architecture. It decouples the core workflow from platform-specific API details, ensuring extensibility and fault tolerance.

## 2. Context & Assumptions
- **Current State:** The system supports Telegram, Instagram, and Email (FetLife).
- **Constraints:** 
  - Publishing latency matters (sequential publishing to 3+ platforms is too slow).
  - One platform failing (e.g., Instagram API down) is a common scenario and must be handled gracefully.

## 3. Requirements
### Functional
- **Interface:** `Publisher` abstract base class.
- **Concurrency:** Parallel execution of enabled publishers.
- **Result Reporting:** Return success/failure/post_ID per platform.
- **Configuration:** Toggle platforms via config file/env vars.

### Non-Functional
- **Isolation:** Exceptions in one publisher must be caught.
- **Performance:** Minimal overhead from the orchestration layer.

## 4. Architecture & Design

### The `Publisher` Interface
Defined in `services.publishers.base`.
```python
class Publisher(ABC):
    @property
    @abstractmethod
    def platform_name(self) -> str: ...
    
    @abstractmethod
    def is_enabled(self) -> bool: ...
    
    @abstractmethod
    async def publish(self, image_path: str, caption: str, context: dict = None) -> PublishResult: ...
```

### Data Model: `PublishResult`
```python
@dataclass
class PublishResult:
    success: bool
    platform: str
    post_id: Optional[str] = None
    error: Optional[str] = None
```

### Orchestration Logic (`WorkflowOrchestrator`)
1.  **Instantiation:** `app.py` creates instances of all publishers (`TelegramPublisher`, `InstagramPublisher`, `EmailPublisher`), injecting their specific configs.
2.  **Filtering:** `orchestrator.execute` filters the list: `enabled = [p for p in publishers if p.is_enabled()]`.
3.  **Execution:**
    ```python
    tasks = [p.publish(...) for p in enabled]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    ```
4.  **Normalization:** Any unhandled exceptions returned by `gather` are converted to failed `PublishResult` objects to keep the result map consistent.

## 5. Platform Specifics

### Telegram (`TelegramPublisher`)
- **Library:** `python-telegram-bot` (Async native).
- **Logic:** `bot.send_photo`.
- **Lifecycle:** Must call `bot.shutdown()` in `finally` block to clean up `aiohttp` sessions.

### Instagram (`InstagramPublisher`)
- **Library:** `instagrapi` (Synchronous).
- **Adapter:** Wrapped in `asyncio.to_thread` to prevent blocking the event loop.
- **Session:** Manages session file load/dump to persist login cookies.
- **Media:** Resizes image to max 1080px width using `Pillow` before upload.

### Email / FetLife (`EmailPublisher`)
- **Library:** `smtplib` (Synchronous).
- **Adapter:** Wrapped in `asyncio.to_thread`.
- **Features:** Handles complex Subject/Body logic based on config (`caption_target`) and sends generic confirmation emails to the user.

## 6. Error Handling
- **Per-Publisher:** Each implementation wraps its logic in `try/except Exception`.
- **Orchestrator:** `asyncio.gather(return_exceptions=True)` serves as a failsafe for crashes.
- **Logging:** Each publisher logs its own start/finish/error duration via `log_publisher_publish`.

## 7. Testing Strategy
- **Unit Tests:**
  - Mock the underlying libraries (`telegram.Bot`, `instagrapi.Client`, `smtplib.SMTP`).
  - Verify `publish` returns correct `PublishResult` on success/failure.
  - Verify `is_enabled` respects config.
- **Integration Tests:**
  - Hard to test real APIs in CI; rely on dry-run/preview mode tests which exercise the orchestration logic but mock the final network call.

## 8. Risks & Mitigations
- **Risk:** `instagrapi` breaks due to Instagram API changes.
  - **Mitigation:** `instagrapi` is updated frequently; use pinned version; isolate failure so it doesn't stop Telegram/Email.
- **Risk:** Blocking calls in async loop.
  - **Mitigation:** Strict use of `asyncio.to_thread` for any blocking I/O (SMTP, synchronous APIs). Code review enforcement.
