--[[
  redis_reserve.lua
  -----------------
  Atomically reserve a contiguous block of seats in a single venue row.

  This script is executed via EVAL/EVALSHA so every step runs inside Redis
  as a single atomic unit — no external locks or multi-step transactions are
  required and no partial state can be observed by concurrent callers.

  Algorithm
  ---------
  1. Read the row bitmap (a plain string of '0'/'1' characters, one char per
     seat — '0' = free, '1' = taken).
  2. Scan the bitmap for every run of `num_seats` consecutive '0' characters
     and collect all starting positions as candidates.
  3. If no candidate run exists, return the error token "NO_BLOCK".
  4. Pick one candidate at random (seeded from Redis's own microsecond clock)
     so that concurrent requests are spread across the row rather than always
     colliding at the leftmost available block.
  5. Flip the chosen positions to '1' and write the updated bitmap back.
  6. Build a JSON array describing the reserved seats (row + index pairs).
  7. Store reservation metadata in a Redis hash and schedule expiry via both
     EXPIRE and a TTL sorted set used by the background expiry worker.
  8. Return {reservation_id, seats_json, expiry_epoch} to the caller.

  Keys
  ----
  KEYS[1]  seats:{event_id}:row:{row_id}:bitmap
             Plain-string bitmap for the row; '0' = free, '1' = taken.

  Arguments
  ---------
  ARGV[1]  num_seats             Number of contiguous seats requested.
  ARGV[2]  reservation_id        UUID for this reservation (caller-generated).
  ARGV[3]  event_id              UUID of the target event.
  ARGV[4]  row_id                Row identifier (e.g. "A", "B") used to build
                                 the seat coordinate JSON.
  ARGV[5]  user_email            Email of the reserving user; stored in the
                                 reservation hash for downstream use.
  ARGV[6]  amount_cents          Total price in cents for the block.
  ARGV[7]  ttl_seconds           Redis EXPIRE value for the reservation hash.
  ARGV[8]  expiry_epoch_seconds  Unix timestamp at which the hold expires;
                                 used as the sorted-set score.

  Return value
  ------------
  On success : {reservation_id, seats_json, expiry_epoch}
  On failure : Redis error table  {err = "NO_BLOCK"}
--]]

-- ── Key / argument bindings ───────────────────────────────────────────────────

local key          = KEYS[1]               -- row bitmap key
local num_seats    = tonumber(ARGV[1])     -- how many consecutive seats needed
local reservation_id = ARGV[2]             -- UUID for this hold
local event_id     = ARGV[3]
local row_id       = ARGV[4]              -- used when building seat JSON
local user_email   = ARGV[5]
local amount_cents = ARGV[6]
local ttl_seconds  = tonumber(ARGV[7])    -- TTL for the reservation hash
local expiry_epoch = tonumber(ARGV[8])    -- score in the TTL sorted set

-- ── Step 1: Load the row bitmap ───────────────────────────────────────────────

local bmp = redis.call('GET', key)
if not bmp then
  -- Bitmap has not been seeded yet; treat the entire row as unavailable.
  return {err='NO_BLOCK'}
end

-- ── Step 2: Find all contiguous free-seat blocks of the requested length ──────

-- Build a pattern of `num_seats` '0' characters to search for in the bitmap.
local pattern    = string.rep('0', num_seats)
local candidates = {}  -- starting positions (1-based) of matching blocks
local pos        = 1

while true do
  -- find() with plain=true avoids Lua pattern-magic character issues.
  local i = string.find(bmp, pattern, pos, true)
  if not i then break end   -- no more matches
  table.insert(candidates, i)
  pos = i + 1               -- advance by 1 to allow overlapping detection
end

-- ── Step 3: Bail out if no block is available ─────────────────────────────────

if #candidates == 0 then
  return {err='NO_BLOCK'}
end

-- ── Step 4: Pick a random candidate for fairness ──────────────────────────────

-- Seed from the microsecond component of Redis TIME so different Redis
-- instances (or rapid successive calls) get different seeds.
math.randomseed(tonumber(redis.call('TIME')[2]))
local pick_i = candidates[math.random(#candidates)]

-- ── Step 5: Flip chosen seats to '1' and write the bitmap back ────────────────

-- Reconstruct the bitmap: prefix | reserved block | suffix
local pre  = ''
if pick_i > 1 then
  pre = string.sub(bmp, 1, pick_i - 1)  -- seats before the chosen block
end

local taken = string.rep('1', num_seats) -- mark chosen seats as taken

local post = ''
if (pick_i + num_seats) <= string.len(bmp) then
  post = string.sub(bmp, pick_i + num_seats)  -- seats after the chosen block
end

local newbmp = pre .. taken .. post
redis.call('SET', key, newbmp)

-- ── Step 6: Build the seats JSON array ────────────────────────────────────────

-- Each element is {"row":"<row_id>","index":<0-based column index>}.
local seats = {}
for i = 0, num_seats - 1 do
  table.insert(seats, string.format('{"row":"%s","index":%d}', row_id, pick_i + i))
end
local seats_json = '[' .. table.concat(seats, ',') .. ']'

-- ── Step 7: Persist reservation metadata and schedule expiry ─────────────────

-- Store all reservation fields in a Redis hash.
redis.call(
  'HMSET', 'reservation:' .. reservation_id,
  'event_id',      event_id,
  'seats',         seats_json,
  'status',        'reserved',
  'user_email',    user_email,
  'amount',        amount_cents,
  'reserved_until', expiry_epoch
)

-- Let Redis auto-expire the hash after ttl_seconds as a safety net.
redis.call('EXPIRE', 'reservation:' .. reservation_id, ttl_seconds)

-- Add to the sorted set so the background expiry worker can find it
-- even if the hash TTL fires before the worker polls.
redis.call('ZADD', 'reservations:ttl', expiry_epoch, reservation_id)

-- ── Step 8: Return result to the caller ───────────────────────────────────────

return {reservation_id, seats_json, expiry_epoch}
