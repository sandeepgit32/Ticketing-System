--[[
Atomically reserve explicit seat indexes in an event bitmap.

Inputs:
  KEYS[1] = seats:{event_id}:bitmap
  KEYS[2] = reservation:{reservation_id}
  KEYS[3] = reservations:ttl

  ARGV[1] = reservation_id
  ARGV[2] = event_id
  ARGV[3] = user_email
  ARGV[4] = expires_epoch_seconds
  ARGV[5] = ttl_seconds
  ARGV[6] = seat_indexes_json (e.g. [0,1,2])

Returns:
  {"OK", reservation_id} on success
  {"ERR", "SEAT_TAKEN"} if any requested seat is already held
  {"ERR", "INVALID_SEATS"} if input is invalid
--]]

local bitmap_key = KEYS[1]
local reservation_key = KEYS[2]
local ttl_key = KEYS[3]

local reservation_id = ARGV[1]
local event_id = ARGV[2]
local user_email = ARGV[3]
local expires_epoch = tonumber(ARGV[4])
local ttl_seconds = tonumber(ARGV[5])
local seat_indexes_json = ARGV[6]

if not expires_epoch or not ttl_seconds then
  return {"ERR", "INVALID_SEATS"}
end

local seat_indexes = cjson.decode(seat_indexes_json)
if not seat_indexes or #seat_indexes == 0 then
  return {"ERR", "INVALID_SEATS"}
end

for i = 1, #seat_indexes do
  local idx = tonumber(seat_indexes[i])
  if idx == nil or idx < 0 then
    return {"ERR", "INVALID_SEATS"}
  end
  local occupied = redis.call("GETBIT", bitmap_key, idx)
  if occupied == 1 then
    return {"ERR", "SEAT_TAKEN"}
  end
end

for i = 1, #seat_indexes do
  redis.call("SETBIT", bitmap_key, tonumber(seat_indexes[i]), 1)
end

redis.call(
  "HSET",
  reservation_key,
  "reservation_id", reservation_id,
  "event_id", event_id,
  "user_email", user_email,
  "seat_indexes", seat_indexes_json,
  "status", "reserved",
  "expires_at", tostring(expires_epoch)
)
redis.call("EXPIRE", reservation_key, ttl_seconds)
redis.call("ZADD", ttl_key, expires_epoch, reservation_id)

return {"OK", reservation_id}
