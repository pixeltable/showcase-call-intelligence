import assert from "node:assert/strict";
import { test } from "node:test";
import { uploadIdentity } from "../src/api/uploadIdentity.js";

function form(bytes = "speech", queue = "billing") {
  const data = new FormData();
  data.set("audio", new Blob([bytes]), "call.wav");
  data.set("call_date", "2026-10-09T00:00:00.000Z");
  data.set("agent_id", " a ");
  data.set("queue", queue);
  return data;
}

test("lost-response retries retain one key for the same bytes and normalized metadata", async () => {
  const first = await uploadIdentity(form(), null);
  const retry = form();
  retry.set("agent_id", "a");
  assert.deepEqual(await uploadIdentity(retry, first), first);
});

test("same filename/size with changed bytes, changed metadata, or a successful new upload rotate the key", async () => {
  const first = await uploadIdentity(form("abc"), null);
  assert.notEqual((await uploadIdentity(form("xyz"), first)).key, first.key);
  assert.notEqual((await uploadIdentity(form("abc", "sales"), first)).key, first.key);
  assert.notEqual((await uploadIdentity(form("abc"), null)).key, first.key);
});
