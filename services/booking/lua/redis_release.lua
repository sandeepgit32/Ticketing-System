--[[
  redis_release.lua
  -----------------
  Atomically release a set of previously held seat indexes from an event bitmap.

  This script is the counterpart to redis_reserve.lua.  It is invoked
  when a reservation expires, is cancelled, or a payment fails, and must undo
  exactly the state that redis_reserve_explicit.lua wrote — no more, no less.

  Algorithm
  ---------
  1. Decode the JSON array of zero-based seat indexes.
  2. For each valid index, clear the corresponding bit in the event bitmap
     (SETBIT … 0), freeing the seat for future reservations.
  3. Delete the reservation metadata hash entirely.
  4. Remove the reservation from the TTL sorted set so the expiry worker
     no longer tracks it.
  5. Return {"OK", reservation_id} to confirm completion.

  Design notes
  ------------
  - Bit-clearing is unconditional: if a bit is already 0 (e.g. the bitmap was
    flushed or the reservation was already released), the operation is a no-op
    and does not cause an error.
  - Deleting a non-existent hash or removing a missing sorted-set member are
    both safe no-ops in Redis, so this script is idempotent.
  - The caller (Python) swallows any exception from this script because Redis is
    the speed layer; inconsistencies are reconciled by the expiry worker on the
    next poll.

  Keys
  ----
  KEYS[1]  seats:{event_id}:bitmap     Per-event bitfield to clear seat bits in.
  KEYS[2]  reservation:{reservation_id} Hash storing reservation metadata to delete.
  KEYS[3]  reservations:ttl            Sorted set to remove the reservation from.

  Arguments
  ---------
  ARGV[1]  reservation_id      UUID of the reservation being released.
  ARGV[2]  seat_indexes_json   JSON array of zero-based seat indexes to free,
                               e.g. [0, 1, 5].

  Return value
  ------------
  {"OK", reservation_id}  — always returned (operation is idempotent).
--]]

-- ── Key / argument bindings ───────────────────────────────────────────────────

local bitmap_key      = KEYS[1]  -- per-event seat bitmap
local reservation_key = KEYS[2]  -- hash holding reservation metadata
local ttl_key         = KEYS[3]  -- sorted set managed by the expiry worker

local reservation_id    = ARGV[1]
local seat_indexes_json = ARGV[2]

-- ── Step 1 & 2: Decode seat indexes and clear each bit ───────────────────────

local seat_indexes = cjson.decode(seat_indexes_json)
if seat_indexes then
  for i = 1, #seat_indexes do
    local idx = tonumber(seat_indexes[i])

    -- Skip any element that is not a valid non-negative integer rather than
    -- erroring out; partial release is better than leaving all bits set.
    if idx ~= nil and idx >= 0 then
      -- Clear bit `idx` in the bitmap, marking the seat as free again.
      redis.call("SETBIT", bitmap_key, idx, 0)
    end
  end
end

-- ── Step 3: Remove the reservation hash ──────────────────────────────────────

-- DEL is a no-op if the key has already been removed (e.g. by Redis TTL).
redis.call("DEL", reservation_key)

-- ── Step 4: Remove from the TTL sorted set ───────────────────────────────────

-- ZREM is a no-op if the member is not present.
redis.call("ZREM", ttl_key, reservation_id)

-- ── Step 5: Confirm completion ────────────────────────────────────────────────

return {"OK", reservation_id}
