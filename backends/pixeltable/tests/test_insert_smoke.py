"""Insert one silent call through the table API and check the no-speech path.

Needs the tables (`pxt schema update app.py call_center`) and WhisperX; Ollama is never called,
because a call with no speech has no transcript and the five LLM cells skip.

    cd backends/pixeltable
    PXT_INSERT_SMOKE=1 uv run python -m unittest tests.test_insert_smoke -v
"""

import os
import struct
import unittest
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory


def _write_silent_wav(path: Path, seconds: float = 1.0, rate: int = 16000) -> None:
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack(f"<{int(rate * seconds)}h", *([0] * int(rate * seconds))))


@unittest.skipUnless(os.getenv("PXT_INSERT_SMOKE", "").lower() in ("1", "true", "yes"), "set PXT_INSERT_SMOKE=1")
class InsertSmokeTest(unittest.TestCase):
    def test_silent_call_completes_without_llm(self) -> None:
        import pixeltable as pxt

        calls = pxt.get_table("call_center.calls")
        call_id = uuid.uuid4()
        with TemporaryDirectory() as tmp:
            wav = Path(tmp) / "silence.wav"
            _write_silent_wav(wav)
            try:
                status = calls.insert(
                    [
                        {
                            "id": call_id,
                            "audio": str(wav),
                            "video": None,
                            "media_type": "audio",
                            "call_date": datetime.now(timezone.utc),
                            "agent_id": "smoke-agent",
                            "customer_id": "smoke-customer",
                            "queue": "smoke",
                            "vertical": "call_center",
                            "original_filename": "silence.wav",
                        }
                    ],
                    on_error="ignore",
                )
                # insert() returns after commit: every column is computed or holds its error.
                self.assertEqual(status.row_count_stats.ins_rows, 1)
                row = (
                    calls.where(calls.id == call_id)
                    .select(
                        calls.transcript,
                        calls.summary,
                        calls.category,
                        calls.sentiment,
                        err=calls.diarized.errormsg,
                        summary_err=calls.summary.errormsg,
                    )
                    .collect()[0]
                )
                self.assertIsNone(row["err"])
                self.assertIsNone(row["summary_err"])
                self.assertIsNone(row["transcript"])
                self.assertEqual(row["summary"], "")
                self.assertEqual(row["category"], "Uncategorized")
                self.assertEqual(row["sentiment"]["label"], "unknown")
            finally:
                calls.delete(where=calls.id == call_id)


if __name__ == "__main__":
    unittest.main()
