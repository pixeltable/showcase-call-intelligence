/** Hash the actual bytes and normalized request fields, rather than filename/size heuristics. */
export async function uploadIdentity(form, previous) {
  const file = form.get("audio");
  if (!(file instanceof Blob)) throw new Error("Choose a recording first.");
  const bytes = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  const mediaHash = Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
  const metadata = Object.fromEntries(Array.from(form.entries())
    .filter(([name]) => name !== "audio")
    .map(([name, value]) => [name, String(value).trim()])
    .sort(([left], [right]) => left.localeCompare(right)));
  const fingerprint = JSON.stringify([file.name, mediaHash, metadata]);
  return previous?.fingerprint === fingerprint ? previous : {fingerprint, key: crypto.randomUUID()};
}
