"""Crash boundaries of local intake, without catalogs, models, or external services."""

import io
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from intake import IntakeError, IntakeStore, IntakeWorker

PIPELINE = {"profile": "core", "summary": "fixture"}
METADATA = {"media_type": "audio", "call_date": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
            "agent_id": "a", "customer_id": "c", "queue": "billing", "vertical": "call_center",
            "original_filename": "fixture.wav"}


def store_at(root, max_pending=2):
    store = IntakeStore(root, max_pending=max_pending, pipeline=PIPELINE)
    store.open()
    return store


def accept(store, *, data=b"speech", key="one", metadata=None):
    return store.accept(io.BytesIO(data), ".wav", metadata or METADATA, key)


def test_concurrent_retries_reserve_one_receipt_and_one_file(tmp_path):
    store = store_at(tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(lambda _: accept(store), range(16)))
        assert len({r["id"] for r in receipts}) == 1
        assert len(store.pending()) == len(list(tmp_path.glob("*.wav"))) == 1
        for options in ({"data": b"different"}, {"metadata": {**METADATA, "queue": "sales"}}):
            with pytest.raises(IntakeError) as error:
                accept(store, **options)
            assert error.value.status == 409
        assert len(list(tmp_path.glob("*.wav"))) == 1
    finally:
        store.close()


def test_capacity_is_atomic_rejections_leave_no_orphan(tmp_path):
    store = store_at(tmp_path, max_pending=1)
    try:
        first = accept(store)
        with pytest.raises(IntakeError) as error:
            accept(store, key="two")
        assert error.value.status == 429
        assert len(list(tmp_path.glob("*.wav"))) == 1
        assert accept(store)["id"] == first["id"]  # a retry is allowed even when full
    finally:
        store.close()


def test_second_writer_is_refused_without_changing_running_receipt(tmp_path):
    store = store_at(tmp_path)
    try:
        first = accept(store)
        store.update(first["id"], "running")
        other = IntakeStore(tmp_path, max_pending=2, pipeline=PIPELINE)
        with pytest.raises(RuntimeError, match="Another service"):
            other.open()
        assert store.get(first["id"])["state"] == "running"
    finally:
        store.close()


@pytest.mark.parametrize("boundary", ["after_receipt", "after_row"])
def test_process_crash_recovers_without_repeating_committed_provider_work(tmp_path, boundary):
    # os._exit bypasses close/finally. The next process must use only persisted evidence.
    script = """
import io,json,os,sys
from pathlib import Path
from intake import IntakeStore,IntakeWorker
root=Path(sys.argv[1]); pipeline=json.loads(sys.argv[2]); metadata=json.loads(sys.argv[3])
store=IntakeStore(root,max_pending=2,pipeline=pipeline);store.open()
receipt=store.accept(io.BytesIO(b'speech'),'.wav',metadata,'one')
if sys.argv[4]=='after_row':
    def insert(row):
        (root/'canonical.json').write_text(json.dumps({'id':str(row['id'])}))
        (root/'provider-count').write_text('1')
        os._exit(23)
    worker=IntakeWorker(store,lambda _:False,insert)
    worker.process(receipt['id'])
os._exit(23)
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), json.dumps(PIPELINE),
                             json.dumps(METADATA), boundary], cwd=Path(__file__).parents[1])
    assert result.returncode == 23
    store = store_at(tmp_path)
    counts = []
    def exists(call_id):
        path = tmp_path / "canonical.json"
        return path.exists() and json.loads(path.read_text())["id"] == str(call_id)
    def insert(row):
        counts.append(row["id"])
        (tmp_path / "canonical.json").write_text(json.dumps({"id": str(row["id"])}))
        return SimpleNamespace(num_excs=0, cols_with_excs=[])
    worker = IntakeWorker(store, exists, insert)
    try:
        receipt = store.pending()[0]
        assert store.media_path(receipt["filename"]).read_bytes() == b"speech"
        worker.start()
        worker.close()
        assert store.get(receipt["id"])["state"] == "stored"
        assert len(counts) == (1 if boundary == "after_receipt" else 0)
        assert accept(store)["id"] == receipt["id"]
    finally:
        store.close()


def test_commit_then_exception_reconciles_and_never_unlinks_media(tmp_path):
    store = store_at(tmp_path)
    receipt = accept(store)
    committed = set()
    def insert(row):
        committed.add(row["id"])
        raise OSError("lost response after commit")
    worker = IntakeWorker(store, committed.__contains__, insert)
    try:
        worker.start()
        worker.close()
        result = store.get(receipt["id"])
        assert result["state"] == "stored" and result["search_readiness"] == "unknown"
        assert store.media_path(receipt["filename"]).exists()
    finally:
        store.close()


def test_failed_work_is_terminal_and_preserves_media_for_explicit_recovery(tmp_path):
    store = store_at(tmp_path)
    receipt = accept(store)
    calls = []
    def insert(row):
        calls.append(row)
        raise RuntimeError("invalid media")
    worker = IntakeWorker(store, lambda _: False, insert)
    worker.start()
    worker.close()
    assert store.get(receipt["id"])["state"] == "failed"
    assert store.media_path(receipt["filename"]).exists()
    store.close()
    reopened = store_at(tmp_path)
    worker = IntakeWorker(reopened, lambda _: False, insert)
    try:
        worker.start()
        worker.close()
        assert len(calls) == 1
        assert "invalid media" in reopened.get(receipt["id"])["error"]
    finally:
        reopened.close()


def test_configuration_drift_requires_review_before_new_provider_calls(tmp_path):
    store = store_at(tmp_path)
    receipt = accept(store)
    store.pipeline = {**PIPELINE, "profile": "full"}
    worker = IntakeWorker(store, lambda _: False, lambda _: pytest.fail("must not call models"))
    try:
        worker.start()
        worker.close()
        assert "configuration changed" in store.get(receipt["id"])["error"]
    finally:
        store.close()


def test_pending_read_delete_guard_and_deleted_key_tombstone(tmp_path):
    store = store_at(tmp_path)
    receipt = accept(store)
    entered, release = threading.Event(), threading.Event()
    def insert(row):
        entered.set()
        assert release.wait(10)
        return SimpleNamespace(num_excs=0, cols_with_excs=[])
    worker = IntakeWorker(store, lambda _: False, insert)
    try:
        worker.start()
        assert entered.wait(10)
        assert store.get(receipt["id"])["state"] == "running"
        with pytest.raises(IntakeError) as error:
            store.delete(receipt["id"])
        assert error.value.status == 409
        release.set()
        worker.close()
        store.delete(receipt["id"])
        with pytest.raises(IntakeError) as error:
            accept(store)
        assert error.value.status == 410
        assert not list(tmp_path.glob("*.wav"))
    finally:
        release.set()
        worker.close()
        store.close()


def test_path_guards_and_search_diagnostics(tmp_path):
    store = store_at(tmp_path)
    receipt = accept(store)
    worker = IntakeWorker(store, lambda _: False,
                          lambda _: SimpleNamespace(num_excs=1, cols_with_excs=["segments_embed"]))
    try:
        for name in ("../escape.wav", "/tmp/escape.wav", "invalid.wav"):
            with pytest.raises(ValueError):
                store.media_path(name)
        worker.start()
        worker.close()
        result = store.get(receipt["id"])
        assert result["search_readiness"] == "failed"
        assert "segments_embed" in result["search_error"]
    finally:
        store.close()


def test_delayed_duplicate_cannot_change_diagnostics_or_resurrect_a_tombstone(tmp_path):
    store = store_at(tmp_path)
    queued_snapshot = accept(store)
    invocations = []
    worker = IntakeWorker(store, lambda _: False,
                          lambda row: invocations.append(row) or SimpleNamespace(num_excs=0, cols_with_excs=[]))
    try:
        worker.process(queued_snapshot["id"])
        assert store.get(queued_snapshot["id"])["search_readiness"] == "ready"
        worker.submit(queued_snapshot)
        worker.close()
        assert store.get(queued_snapshot["id"])["search_readiness"] == "ready"
        store.delete(queued_snapshot["id"])
        worker = IntakeWorker(store, lambda _: False,
                              lambda row: invocations.append(row) or SimpleNamespace(num_excs=0, cols_with_excs=[]))
        worker.submit(queued_snapshot)
        worker.close()
        assert store.get(queued_snapshot["id"])["state"] == "deleted"
        assert len(invocations) == 1
        assert not list(tmp_path.glob("*.wav"))
    finally:
        worker.close()
        store.close()
