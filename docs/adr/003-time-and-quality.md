# ADR 003: UTC nanosecond timestamps and three quality states

Status: accepted (2026-10-10)

All timestamps are UTC, `timestamp[ns, UTC]` in Arrow (int64 nanoseconds since the epoch); no time zones in data.
Quality is `0 Good`, `1 Uncertain`, `2 Bad`, mapped from OPC UA status codes. Simulator samples are taken before each
step, so sample `k` has time `k * dt`. Consequence: display layers convert to local time; data never does.
