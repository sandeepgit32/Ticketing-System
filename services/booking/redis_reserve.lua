--[[
Redis Lua script used by the booking service to atomically reserve a
contiguous block of seats in a single row for an event.  Executed with
EVAL/EVALSHA so all operations run inside Redis, avoiding races and the
need for external locking.

Inputs:
  KEYS[1]  - seats:{event_id}:row:{row_id}:bitmap  (string bitmap)
  ARGV[1]  - num_seats (number of contiguous seats requested)
  ARGV[2]  - reservation_id (unique identifier for the reservation)
  ARGV[3]  - event_id
  ARGV[4]  - row_id
  ARGV[5]  - user_email
  ARGV[6]  - amount_cents
  ARGV[7]  - ttl_seconds (how long the reservation key should live)
  ARGV[8]  - expiry_epoch_seconds (when the reservation expires)
  ARGV[9]  - seats_per_row (length of the bitmap string)

Behavior:
  * Loads or initializes the bitmap, searches for a run of zeroes of the
    requested length, picks a random candidate for fairness, flips those
    bits to ones and stores the updated bitmap.
  * Constructs a JSON array of the reserved seat coordinates.
  * Creates a hash under ``reservation:<id>`` with fields for event,
    seats, status, user, amount and expiry, sets an expire, and adds the
    expiry to a sorted set for cleanup.
  * Returns the reservation id, seats JSON, and expiry time or an error
    string ``NO_BLOCK`` if no suitable block was available.
--]]

-- Redis Lua script: reserve contiguous seats in a single row
-- KEYS[1] = seats:{event_id}:row:{row_id}:bitmap
-- ARGV[1] = num_seats
-- ARGV[2] = reservation_id
-- ARGV[3] = event_id
-- ARGV[4] = row_id
-- ARGV[5] = user_email
-- ARGV[6] = amount_cents
-- ARGV[7] = ttl_seconds
-- ARGV[8] = expiry_epoch_seconds
-- ARGV[9] = seats_per_row

local key = KEYS[1]
local num_seats = tonumber(ARGV[1])
local reservation_id = ARGV[2]
local event_id = ARGV[3]
local row_id = ARGV[4]
local user_email = ARGV[5]
local amount_cents = ARGV[6]
local ttl_seconds = tonumber(ARGV[7])
local expiry_epoch = tonumber(ARGV[8])
local seats_per_row = tonumber(ARGV[9])

local bmp = redis.call('GET', key)
if not bmp then
  bmp = string.rep('0', seats_per_row)
end

local pattern = string.rep('0', num_seats)
local candidates = {}
local pos = 1
while true do
  local i = string.find(bmp, pattern, pos, true)
  if not i then break end
  table.insert(candidates, i)
  pos = i + 1
end

if #candidates == 0 then
  return {err='NO_BLOCK'}
end

-- pick random candidate for fairness
math.randomseed(tonumber(redis.call('TIME')[2]))
local pick_i = candidates[math.random(#candidates)]
local pre = ''
if pick_i > 1 then pre = string.sub(bmp, 1, pick_i - 1) end
local taken = string.rep('1', num_seats)
local post = ''
if (pick_i + num_seats) <= string.len(bmp) then post = string.sub(bmp, pick_i + num_seats) end
local newbmp = pre .. taken .. post
redis.call('SET', key, newbmp)

local seats_json = ''
-- build seats list
local seats = {}
for i = 0, num_seats - 1 do
  table.insert(seats, string.format('{"row":"%s","index":%d}', row_id, pick_i + i))
end
seats_json = '[' .. table.concat(seats, ',') .. ']'

redis.call('HMSET', 'reservation:'..reservation_id, 'event_id', event_id, 'seats', seats_json, 'status', 'reserved', 'user_email', user_email, 'amount', amount_cents, 'reserved_until', expiry_epoch)
redis.call('EXPIRE', 'reservation:'..reservation_id, ttl_seconds)
redis.call('ZADD', 'reservations:ttl', expiry_epoch, reservation_id)

return {reservation_id, seats_json, expiry_epoch}
