"""Local SQLite session log -- every real session (device power-on through the next "Reset"/
"New Session" trigger or app shutdown) gets written here: a UUID, start/end times, a
placeholder location (no real GPS on this device yet, so a random real Indian pincode is
sampled from this project's own weather DB instead), and the full turn-by-turn transcript --
ready for a future cloud-sync job to pick up (see the `uploaded` column) but not implementing
that job itself here.

Owned by MemoryOrchestrator (api_server/orchestrator.py), not the calling app -- session
lifecycle (start/record-turn/persist/reset) is orchestrator-level state, the same tier as the
memory/component lifecycle it already owns, not something every caller (gramsahayak_app.py, a
test script, ...) should have to reimplement itself. A session gets persisted on THREE real
triggers, all via the orchestrator: `teardown()` (app/process shutting down),
`reset_conversation()` (farmer pressed "Reset" -- cheap, no reload), and `start_new_session()`
(farmer pressed "New Session" -- persist + a real full reload/re-warm). See orchestrator.py's
own methods for the real integration -- this module is just the storage/pincode-sampling
mechanics.

2026-08-14: earlier this same day, a SEPARATE attempt at this same feature was built directly
inside suno-sutra-sw/python/pocketinfer/ (session_store.py there + gramsahayak_app.py's own
_current_session/_persist_current_session/_start_new_session) -- real, working code, but the
wrong layer: pocketinfer is a sibling checkout of a DIFFERENT app, and putting session-lifecycle
logic there meant only that one app could ever trigger a persist, and every future caller
(another app, a test script exercising multi-turn behavior) would have needed its own copy.
Moved here instead, per direct instruction, superseding that version -- see
suno-sutra-sw/python/pocketinfer/SESSION_LOGGING_PLAN.md for the original design notes (schema/
reasoning still accurate, just built in the wrong place).

DB lives inside THIS checkout's own datasets/ tree (datasets/sessionsDB/sessions.sqlite,
config.AGENTS_DIR-relative), not home-relative -- per direct instruction. Real consequence
worth knowing: a fresh `git clone` redeploy starts with an empty sessions DB, and
datasets/sessionsDB/ needs a .gitignore entry (added alongside this file) so a real session's
data is never accidentally committed.
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
from datetime import datetime, timezone

from api_server import config

DEFAULT_DB_PATH = os.path.join(config.AGENTS_DIR, "datasets", "sessionsDB", "sessions.sqlite")
WEATHER_DB_PATH = os.path.join(config.AGENTS_DIR, "datasets", "weather", "full_weather.sqlite")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id       TEXT PRIMARY KEY,   -- uuid4 hex, generated when the session STARTS
    started_at       TEXT NOT NULL,      -- ISO 8601
    ended_at         TEXT NOT NULL,      -- ISO 8601, when persisted (Reset / New Session / shutdown)
    pincode          TEXT,               -- placeholder location, see sample_random_pincode()
    state            TEXT,               -- denormalized from pincode_grid -- avoids re-opening
    district         TEXT,               -- the weather DB just to know where a session logged
    num_turns        INTEGER NOT NULL,
    input_language   TEXT,               -- settings AT SESSION END -- a farmer can switch
    output_language  TEXT,               -- language mid-session, so this is "language when it
                                          -- ended", not a source of truth for the whole session
                                          -- -- that's per-turn, inside transcript_json
    transcript_json  TEXT NOT NULL,      -- json.dumps(session["turns"])
    uploaded         INTEGER NOT NULL DEFAULT 0  -- 0/1 -- a future cloud-sync job does
                                                  -- `WHERE uploaded = 0`, marks 1 after success
);
"""


class SessionStore:
    """Thin, synchronous sqlite3 wrapper -- no ORM, matches this project's existing sqlite
    usage elsewhere (e.g. agent/tools/weather_tools/db.py). A session save is one small INSERT
    of already-in-memory data (English text + short tool-call records, not audio/images), so
    this is fast enough to run synchronously on whatever call triggers it (Reset/New Session/
    teardown) -- no background-thread/queue machinery needed for this."""

    def __init__(self, db_path: str | None = None, log_fn=None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.log_fn = log_fn or (lambda *a, **k: None)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(_SCHEMA)
            con.commit()
        finally:
            con.close()

    def save(self, session: dict, ended_at: str | None = None,
              input_language: str | None = None, output_language: str | None = None) -> None:
        """Persists one session. `session` is the shape MemoryOrchestrator._new_session_dict()
        builds: session_id/started_at/pincode/state/district/turns[]. `INSERT OR REPLACE` (not
        plain INSERT) so a caller can safely save the same session_id twice (e.g. a retry)
        without a primary-key error -- session_id is a fresh uuid4 per session, so this is
        never an accidental overwrite of a DIFFERENT session's row.

        2026-08-21: orchestrator.py's `record_turn()` now calls this after EVERY turn (real
        crash-resilience fix, see that method's own docstring), not just once at session end --
        worth knowing for whoever builds the cloud-sync job the `uploaded` column above is
        for: every call here, including these new incremental ones, hardcodes `uploaded=0` (see
        the VALUES clause below). So if a sync job ever picks up and uploads a session WHILE
        it's still in progress (turn 2 of an eventual 5, say), the FOLLOWING turn's own
        `record_turn()` call will silently reset `uploaded` back to 0 on that same row -- not
        a bug, just means a sync job needs to be fine with re-uploading a session it already
        saw (idempotent on session_id on the receiving end), not assume `uploaded=1` is
        permanent the moment it's set."""
        turns = session.get("turns", [])
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                """
                INSERT OR REPLACE INTO sessions
                    (session_id, started_at, ended_at, pincode, state, district, num_turns,
                     input_language, output_language, transcript_json, uploaded)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    session["session_id"],
                    session["started_at"],
                    ended_at or now_iso(),
                    session.get("pincode"),
                    session.get("state"),
                    session.get("district"),
                    len(turns),
                    input_language,
                    output_language,
                    json.dumps(turns, ensure_ascii=False),
                ),
            )
            con.commit()
        finally:
            con.close()
        self.log_fn(f"        session {session.get('session_id')} persisted "
                    f"({len(turns)} turn(s)) -> {self.db_path}")


# Loaded once per process (module-level cache), not re-queried per session -- sampling a
# placeholder location fires on every Reset/New Session, and pincode_grid is small enough
# (20,308 rows) to hold entirely in memory rather than a fresh `ORDER BY RANDOM()` (a full
# table scan) every single time.
_PINCODE_CACHE: list[tuple] | None = None


def _load_pincode_rows(weather_db_path=WEATHER_DB_PATH) -> list[tuple]:
    global _PINCODE_CACHE
    if _PINCODE_CACHE is None:
        con = sqlite3.connect(weather_db_path)
        try:
            _PINCODE_CACHE = con.execute(
                "SELECT Pincode, StateName, District FROM pincode_grid"
            ).fetchall()
        finally:
            con.close()
    return _PINCODE_CACHE


def sample_random_pincode(weather_db_path=WEATHER_DB_PATH):
    """Placeholder location -- no real GPS on this device yet. Samples one real Indian
    (pincode, state, district) triple from this project's own weather DB
    (datasets/weather/full_weather.sqlite, table pincode_grid -- 20,308 rows, 19,258 distinct
    real pincodes) via random.choice() over a process-wide cached row list. Returns
    (pincode, state, district); raises whatever sqlite3 raises if the DB file/table doesn't
    exist -- callers that want this non-fatal (an empty pincode is fine, it's a placeholder
    either way) should catch around the call, see orchestrator.py's `_new_session_dict()`."""
    rows = _load_pincode_rows(weather_db_path)
    if not rows:
        return None, None, None
    return random.choice(rows)
