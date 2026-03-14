--[[
Atomically release explicit seat indexes from an event bitmap.

Inputs:
  KEYS[1] = seats:{event_id}:bitmap
  KEYS[2] = reservation:{reservation_id}
  KEYS[3] = reservations:ttl

  ARGV[1] = reservation_id
  ARGV[2] = seat_indexes_json (e.g. [0,1,2])

Returns:
  {"OK", reservation_id}
--]]

local bitmap_key = KEYS[1]
local reservation_key = KEYS[2]
local ttl_key = KEYS[3]

local reservation_id = ARGV[1]
local seat_indexes_json = ARGV[2]

local seat_indexes = cjson.decode(seat_indexes_json)
if seat_indexes then
  for i = 1, #seat_indexes do
    local idx = tonumber(seat_indexes[i])
    if idx ~= nil and idx >= 0 then
      redis.call("SETBIT", bitmap_key, idx, 0)
    end
  end
end

redis.call("DEL", reservation_key)
redis.call("ZREM", ttl_key, reservation_id)

return {"OK", reservation_id}
