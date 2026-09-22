"""Smoke test: catalog insert succeeds and pipeline reaches a terminal status.

Run with schema initialized and dependencies up (Ollama, WhisperX):

    cd backends/pixeltable
    PXT_INSERT_SMOKE=1 uv run python -m unittest tests.test_insert_smoke -v
"""

from __future__ import annotations

import os
import struct
import sys
import time
import unittest
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backends" / "pixeltable"))

os.environ.setdefault(
    "PIXELTABLE_HOME",
    str(ROOT / "data" / "pixeltable"),
)


def _write_silent_wav(path: Path, *, seconds: float = 1.0, sample_rate: int = 16000) -> None:
    n_frames = int(sample_rate * seconds)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(struct.pack(f"<{n_frames}h", *([0] * n_frames)))


@unittest.skipUnless(
    os.getenv("PXT_INSERT_SMOKE", "").lower() in ("1", "true", "yes"),
    "Set PXT_INSERT_SMOKE=1 to run catalog insert smoke test",
)
class InsertSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import schema  # noqa: F401
        import pixeltable as pxt

        required = {"call_center/calls", "call_center/transcript_segments"}
        if not required.issubset(set(pxt.list_tables())):
            raise unittest.SkipTest("Pixeltable schema not initialized — run schema.py first")

    def test_insert_reaches_terminal_pipeline_status(self) -> None:
        import config
        import pixeltable as pxt

        calls = pxt.get_table(f"{config.APP_NAMESPACE}.calls")
        before = calls.count()

        call_id = uuid.uuid4()
        wav_path = Path(os.environ.get("TMPDIR", "/tmp")) / f"pxt-smoke-{call_id}.wav"
        try:
            _write_silent_wav(wav_path)
            row = {
                "uuid": call_id,
                "audio": str(wav_path),
                "video": None,
                "media_type": "audio",
                "call_date": datetime.now(timezone.utc),
                "agent_id": "smoke-agent",
                "customer_id": "smoke-customer",
                "queue": "smoke",
                "vertical": "call_center",
                "duration_sec": None,
                "original_filename": "smoke.wav",
            }
            status = calls.insert([row])
            self.assertEqual(status.num_rows, 1)

            deadline = time.monotonic() + float(os.getenv("PXT_INSERT_SMOKE_TIMEOUT", "300"))
            pipeline_status: str | None = None
            while time.monotonic() < deadline:
                if calls.count() < before + 1:
                    time.sleep(2)
                    continue
                rows = (
                    calls.where(calls.uuid == call_id)
                    .select(calls.pipeline_status)
                    .collect()
                )
                if rows is None or len(rows) == 0:
                    time.sleep(2)
                    continue
                pipeline_status = rows[0]["pipeline_status"]
                if pipeline_status in ("completed", "failed"):
                    break
                time.sleep(5)

            self.assertGreaterEqual(
                calls.count(),
                before + 1,
                "Insert did not add a catalog row",
            )
            self.assertIn(
                pipeline_status,
                ("completed", "failed"),
                f"Pipeline did not reach terminal status within timeout (last={pipeline_status!r})",
            )
        finally:
            try:
                calls.delete(calls.uuid == call_id)
            except Exception:
                pass
            wav_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
