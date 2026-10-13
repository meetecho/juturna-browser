// Closes a queue ring of the browser transport from outside Python.
//
// The layout is the one of the browser transport of Juturna: a header of int32
// (the fourth is the CLOSED flag), then the slots, each starting with 9 int32
// (the last is the sequence number producers and the consumer wait on) followed
// by the metadata and payload areas. The header has 7 int32 in Juturna 2.x and
// 8 in 3.x: its length is read from the size of the buffer, not assumed.
const CLOSED = 3;
const SLOT_META_INT32 = 9;
const SLOT_SEQ = 8;

// int32 before the first slot, from what is left of the buffer after the slots
function layout({ sab, capacity, max_meta_json_bytes, max_payload_bytes }) {
  const slotBytes = SLOT_META_INT32 * 4 + max_meta_json_bytes + max_payload_bytes;
  const headerBytes = sab.byteLength - capacity * slotBytes;
  if (!Number.isInteger(headerBytes / 4) || headerBytes < 28) {
    throw new Error(`unknown queue layout: ${sab.byteLength} bytes for ${capacity} slots of ${slotBytes}`);
  }
  return { slotBytes, headerInt32: headerBytes / 4 };
}

/**
 * Close a ring so that nobody stays blocked on it: a writer waiting for room
 * gets a `QueueClosed` error instead, a reader still gets what the ring holds.
 * Used when the Worker at the other end is gone.
 * @param {{sab: SharedArrayBuffer, capacity: number, max_meta_json_bytes: number,
 *   max_payload_bytes: number}} handle what `queue_handle()` returned
 */
export function poisonRing(handle) {
  const { slotBytes, headerInt32 } = layout(handle);
  const cells = new Int32Array(handle.sab);
  Atomics.store(cells, CLOSED, 1);

  for (let slot = 0; slot < handle.capacity; slot++) {
    Atomics.notify(cells, headerInt32 + slot * slotBytes / 4 + SLOT_SEQ);
  }
}

const HEAD = 0;
const TAIL = 1;
const COUNT = 2;

// The tickets a producer claimed and never published: from the reader's
// position to the head, the slots whose sequence number is still the ticket.
function abandoned(cells, handle) {
  const { capacity } = handle;
  const { slotBytes, headerInt32 } = layout(handle);
  const head = Atomics.load(cells, HEAD);
  const found = [];
  for (let ticket = Atomics.load(cells, TAIL); ticket !== head && found.length <= capacity; ticket = (ticket + 1) | 0) {
    const first = headerInt32 + ((ticket >>> 0) % capacity) * slotBytes / 4;
    if (Atomics.load(cells, first + SLOT_SEQ) === ticket) found.push({ ticket, first });
  }
  return found;
}

/**
 * Fill in the slots that a producer that died left claimed and unpublished,
 * which would keep the reader of the ring waiting for ever: each gets an empty
 * slot, that the reader skips. Call it only once the producer is gone.
 *
 * A producer alive claims a slot for the time of a write, so a slot is repaired
 * only if it stays claimed and unpublished for `graceMs`.
 * @returns {Promise<number>} how many slots were repaired
 */
export async function repairRing(handle, { graceMs = 250 } = {}) {
  const cells = new Int32Array(handle.sab);
  const first = abandoned(cells, handle);
  if (!first.length) return 0;

  await new Promise((resolve) => setTimeout(resolve, graceMs));

  const still = new Set(abandoned(cells, handle).map(({ ticket }) => ticket));
  let repaired = 0;
  for (const { ticket, first: base } of first) {
    if (!still.has(ticket)) continue;
    for (let word = 0; word < SLOT_SEQ; word++) Atomics.store(cells, base + word, 0);   // no metadata: nothing to read
    Atomics.store(cells, base + SLOT_SEQ, (ticket + 1) | 0);
    Atomics.add(cells, COUNT, 1);
    Atomics.notify(cells, base + SLOT_SEQ);
    repaired++;
  }
  return repaired;
}
