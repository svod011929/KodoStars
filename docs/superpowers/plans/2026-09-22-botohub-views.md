# BotoHub Views Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox syntax.

**Goal:** Integrate BotoHub Views ad impressions (hi on first /start + ads after earn).

**Architecture:** Thin `botohub_views` service + fire-and-forget hooks; runtime settings include token.

**Tech Stack:** aiogram 3, aiohttp via `app.op.http`, pydantic-settings, pytest.

## Global Constraints

- Authorization header = raw token (no Bearer).
- Fail-open on any non-success.
- Russian UI labels for runtime settings.
- Do not touch PiarFlow OP cascade.

---

### Task 1: Config + service + unit tests

**Files:** `app/config.py`, `.env.example`, `app/services/botohub_views.py`, `tests/test_botohub_views.py`

- [ ] Add 4 settings to Settings + RUNTIME_OVERRIDABLE/LABELS + non-negative validator for cooldown
- [ ] Implement send/cooldown/schedule helpers
- [ ] Unit tests with mocked post_json
- [ ] Commit

### Task 2: Handler hooks + docs

**Files:** `app/bot/handlers/start.py`, `earn.py`, `promo.py`, `README.md`

- [ ] Wire hi / ad after success paths
- [ ] README short section + .env.example
- [ ] Fix accidental duplicate `_FALSE` in `app_settings.py` if still present
- [ ] Commit
