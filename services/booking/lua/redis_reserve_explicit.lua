--[[
  redis_reserve.lua
  -----------------
  Atomically reserve a caller-specified set of seat indexes in an event bitmap.

  This script accepts a caller-specified list of zero-based seat indexes and either
  reserves all of them or rejects the entire request — there is no partial hold.

  Algorithm
  ---------
  1. Validate all inputs (expiry timestamp, TTL, and seat index list).
  2. In a first pass, check each requested bit in the event bitmap.
     If any bit is already set (seat taken), abort immediately with
     "SEAT_TAKEN" — no writes have occurred at this point.
  3. In a second pass (only reached when all seats are free), set each
     bit to 1, marking the seats as held.
  4. Write reservation metadata into a Redis hash and schedule expiry
     via both EXPIRE and the TTL sorted set used by the expiry worker.
  5. Return {"OK", reservation_id} to the caller.

  Keys
  ----
  KEYS[1]  seats:{event_id}:bitmap     Per-event bitfield; bit N represents seat N.
  KEYS[2]  reservation:{reservation_id} Hash storing reservation metadata.
  KEYS[3]  reservations:ttl            Sorted set used as a TTL index by the
                                       background expiry worker.

  Arguments
  ---------
  ARGV[1]  reservation_id        UUID for this reservation (caller-generated).
  ARGV[2]  event_id              UUID of the target event.
  ARGV[3]  user_email            Email of the reserving user.
  ARGV[4]  expires_epoch_seconds Unix timestamp when the hold expires; used as
                                 the sorted-set score.
  ARGV[5]  ttl_seconds           Seconds until the reservation hash auto-expires.
  ARGV[6]  seat_indexes_json     JSON array of zero-based integer seat indexes,
                                 e.g. [0, 1, 5].

  Return values
  -------------
  {"OK",  reservation_id}  — all seats successfully reserved.
  {"ERR", "INVALID_SEATS"} — input validation failed (bad JSON, empty list,
                             negative index, or non-numeric expiry/TTL).
  {"ERR", "SEAT_TAKEN"}    — at least one requested seat was already held;
                             no state was modified.
--]]

-- ── Key / argument bindings ───────────────────────────────────────────────────

local bitmap_key      = KEYS[1]  -- per-event seat bitmap
local reservation_key = KEYS[2]  -- hash key for this reservation's metadata
local ttl_key         = KEYS[3]  -- sorted set used by the expiry worker

local reservation_id    = ARGV[1]
local event_id          = ARGV[2]
local user_email        = ARGV[3]
local expires_epoch     = tonumber(ARGV[4])  -- nil if non-numeric
local ttl_seconds       = tonumber(ARGV[5])  -- nil if non-numeric
local seat_indexes_json = ARGV[6]

-- ── Step 1: Input validation ──────────────────────────────────────────────────

-- Both numeric arguments must be present and parseable.
if not expires_epoch or not ttl_seconds then
  return {"ERR", "INVALID_SEATS"}
end

-- Decode the seat index list; reject missing or empty arrays.
local seat_indexes = cjson.decode(seat_indexes_json)
if not seat_indexes or #seat_indexes == 0 then
  return {"ERR", "INVALID_SEATS"}
end

-- ── Step 2: Conflict check (read-only pass) ───────────────────────────────────

-- Iterate every requested seat index before making any writes.
-- This ensures the operation is all-or-nothing: if any seat is taken we bail
-- without having modified the bitmap.
for i = 1, #seat_indexes do
  local idx = tonumber(seat_indexes[i])

  -- Reject non-numeric or negative indexes.
  if idx == nil or idx < 0 then
    return {"ERR", "INVALID_SEATS"}
  end

  -- GETBIT returns 1 if the seat is already held, 0 if free.
  local occupied = redis.call("GETBIT", bitmap_key, idx)
  if occupied == 1 then
    return {"ERR", "SEAT_TAKEN"}  -- abort: do not write anything
  end
end

-- ── Step 3: Mark seats as held (write pass) ───────────────────────────────────

-- All seats were free; set each bit to 1 atomically within this script.
for i = 1, #seat_indexes do
  redis.call("SETBIT", bitmap_key, tonumber(seat_indexes[i]), 1)
end

-- ── Step 4: Persist reservation metadata and schedule expiry ─────────────────

-- Store all reservation fields in a dedicated Redis hash.
redis.call(
  "HSET",
  reservation_key,
  "reservation_id", reservation_id,
  "event_id",       event_id,
  "user_email",     user_email,
  "seat_indexes",   seat_indexes_json,  -- kept as JSON for easy retrieval
  "status",         "reserved",
  "expires_at",     tostring(expires_epoch)
)

-- Auto-expire the hash after ttl_seconds as a memory safety net.
redis.call("EXPIRE", reservation_key, ttl_seconds)

-- Register in the sorted set so the background worker can sweep expired
-- reservations even when the hash TTL fires before the worker polls.
redis.call("ZADD", ttl_key, expires_epoch, reservation_id)

-- ── Step 5: Return success ────────────────────────────────────────────────────

return {"OK", reservation_id}
