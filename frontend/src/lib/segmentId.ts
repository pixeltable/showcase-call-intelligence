/** Client-side segment anchors for the Pixeltable UI (pos-based; no server UUID mapping). */

export function segmentUuid(callId: string, pos: number): string {
  return `${callId}:${pos}`;
}
