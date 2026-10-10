"""Local durable upload receipts; no provider work happens before a receipt commits.

SQLite owns admission/idempotency, fsynced UUID files own media, and one service process owns
the writer lock. This is a single-machine spool, not an exactly-once external-effects queue.
"""

import fcntl
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class IntakeError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail
        super().__init__(detail)


class IntakeStore:
    def __init__(self, root: Path, *, max_pending: int, pipeline: dict):
        self.root, self.max_pending, self.pipeline = root, max_pending, pipeline
        self.directory = root / ".intake"
        self.database = self.directory / "receipts.sqlite3"
        self._lock = None

    def open(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.directory.is_symlink():
            raise RuntimeError("The intake directory must not be a symlink")
        self.directory.mkdir(mode=0o700, exist_ok=True)
        descriptor = os.open(self.directory / "writer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(descriptor)
            raise RuntimeError("Another service owns this upload spool; use one writer or a separate upload directory") from exc
        self._lock = descriptor
        try:
            if self.database.is_symlink():
                raise RuntimeError("The receipt database must not be a symlink")
            with self.connection() as db:
                db.execute("CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, key_hash TEXT UNIQUE, "
                           "fingerprint TEXT NOT NULL, filename TEXT NOT NULL, metadata TEXT NOT NULL, "
                           "pipeline TEXT NOT NULL, state TEXT NOT NULL, error TEXT, search_readiness TEXT NOT NULL, "
                           "search_error TEXT)")
            os.chmod(self.database, 0o600)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self._lock is not None:
            os.close(self._lock)
            self._lock = None

    @contextmanager
    def connection(self):
        if self._lock is None:
            raise RuntimeError("Upload intake is not running")
        with sqlite3.connect(self.database, timeout=10) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=FULL")
            yield db

    def media_path(self, filename: str) -> Path:
        if not re.fullmatch(r"[0-9a-f-]{36}\.[a-z0-9]+", filename):
            raise ValueError("Invalid receipt media filename")
        uuid.UUID(filename.split(".")[0])
        path = self.root / filename
        if path.is_symlink():
            raise ValueError("Receipt media must not be a symlink")
        return path

    def accept(self, stream, suffix: str, metadata: dict, key: str | None) -> dict:
        """Stage durable bytes, then atomically deduplicate and reserve bounded pending capacity."""
        call_id = str(uuid.uuid4())
        filename = f"{call_id}{suffix}"
        dest = self.media_path(filename)
        serialized = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(serialized.encode())
        digest.update(suffix.encode())
        try:
            with dest.open("xb") as out:
                os.chmod(dest, 0o600)
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            descriptor = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            key_hash = hashlib.sha256(key.encode()).hexdigest() if key else None
            with self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                if key_hash:
                    existing = db.execute("SELECT * FROM receipts WHERE key_hash=?", (key_hash,)).fetchone()
                    if existing:
                        if existing["fingerprint"] != digest.hexdigest():
                            raise IntakeError(409, "Idempotency key was already used for different media or metadata")
                        if existing["state"] == "deleted":
                            raise IntakeError(410, "This idempotent upload was deleted; use a new key for a new call")
                        dest.unlink()
                        return dict(existing)
                count = db.execute("SELECT count(*) FROM receipts WHERE state IN ('queued','running')").fetchone()[0]
                if count >= self.max_pending:
                    raise IntakeError(429, "Upload queue is full; retry later with the same idempotency key")
                db.execute("INSERT INTO receipts VALUES (?,?,?,?,?,?,'queued',NULL,'pending',NULL)",
                           (call_id, key_hash, digest.hexdigest(), filename, serialized,
                            json.dumps(self.pipeline, sort_keys=True)))
            # From this point on, never remove the media even if a later receipt read fails.
        except BaseException:
            # A commit may have succeeded before an exception. Reconcile before orphan cleanup.
            with self.connection() as db:
                accepted = db.execute("SELECT id FROM receipts WHERE id=?", (call_id,)).fetchone()
            if not accepted:
                dest.unlink(missing_ok=True)
            raise
        return self.get(call_id)

    def get(self, call_id) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM receipts WHERE id=?", (str(call_id),)).fetchone()
        return dict(row) if row else None

    def pending(self) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM receipts WHERE state IN ('queued','running')")]

    def update(self, call_id, state: str, *, error=None, search_readiness="unknown", search_error=None):
        with self.connection() as db:
            db.execute("UPDATE receipts SET state=?,error=?,search_readiness=?,search_error=? WHERE id=?",
                       (state, error, search_readiness, search_error, str(call_id)))

    def row(self, receipt: dict) -> dict:
        metadata = json.loads(receipt["metadata"])
        metadata["call_date"] = datetime.fromisoformat(metadata["call_date"])
        video = metadata["media_type"] == "video"
        path = str(self.media_path(receipt["filename"]))
        return {**metadata, "id": uuid.UUID(receipt["id"]), "audio": None if video else path,
                "video": path if video else None}

    def delete(self, call_id):
        receipt = self.get(call_id)
        if receipt and receipt["state"] in {"queued", "running"}:
            raise IntakeError(409, "This upload is still processing; wait before deleting it")
        if receipt:
            self.update(call_id, "deleted")
            self.media_path(receipt["filename"]).unlink(missing_ok=True)


class IntakeWorker:
    def __init__(self, store: IntakeStore, exists, insert):
        self.store, self.exists, self.insert = store, exists, insert
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pxt-intake")
        self.submitted = set()
        # submit() is called by concurrent upload handlers; guard the in-process set only.
        self.guard = threading.Lock()

    def start(self):
        for receipt in self.store.pending():
            self.submit(receipt)

    def submit(self, receipt):
        with self.guard:
            if receipt["id"] not in self.submitted and receipt["state"] in {"queued", "running"}:
                self.submitted.add(receipt["id"])
                self.executor.submit(self.process, receipt["id"])

    def process(self, call_id):
        try:
            receipt = self.store.get(call_id)
            if receipt is None or receipt["state"] not in {"queued", "running"}:
                return  # A delayed duplicate may carry an old queued snapshot after completion/deletion.
            # Resolve the canonical row before any provider call or recovery decision.
            if self.exists(uuid.UUID(call_id)):
                self.store.update(call_id, "stored")
                return
            if json.loads(receipt["pipeline"]) != self.store.pipeline:
                raise RuntimeError("Accepted pipeline configuration changed; review it, then delete the failed upload "
                                   "and submit a new request after fixing the configuration")
            self.store.update(call_id, "running", search_readiness="pending")
            status = self.insert(self.store.row(receipt))
            error = (f"{status.num_excs} computed/index cell errors in {status.cols_with_excs}"
                     if status.num_excs else None)
            self.store.update(call_id, "stored", search_readiness="failed" if error else "ready", search_error=error)
            if error:
                logger.warning("Call %s committed with %s", call_id, error)
        except Exception as exc:
            # The insert may have committed before it raised. Never delete its media or run it twice.
            try:
                committed = self.exists(uuid.UUID(call_id))
                self.store.update(call_id, "stored" if committed else "failed",
                                  error=None if committed else f"{type(exc).__name__}: {exc}")
            except Exception:
                logger.exception("Receipt %s needs reconciliation on the next service start", call_id)
        finally:
            with self.guard:
                self.submitted.discard(call_id)

    def close(self):
        self.executor.shutdown(wait=True)
