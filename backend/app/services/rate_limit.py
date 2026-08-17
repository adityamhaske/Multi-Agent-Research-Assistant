"""
Atomic rate limiting (docs/architecture/06-security.md §2).

One Lua script does INCR + conditional EXPIRE atomically, so a counter can never
exist without a TTL (the previous iteration's INCR-then-EXPIRE could strand a user
forever). Keys are per-operation so research starts and chat messages never share a
budget.
"""

from __future__ import annotations

from dataclasses import dataclass

# KEYS[1]=key  ARGV[1]=limit  ARGV[2]=window_seconds
# Returns {current_count, ttl_seconds}. Sets TTL on first increment.
_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


@dataclass(frozen=True)
class RateLimit:
    limit: int
    window_seconds: int


# Per-operation limits (docs/06 §2).
#
# Auth limits are brute-force protection and are NOT configurable — an operator must not
# be able to disable credential-stuffing defence while raising a usage cap.
#
# Research and chat limits are deliberately absent: they are abuse guards for a
# multi-tenant host, not safety limits, so they are built per-request from
# `Settings.research_rate_limit_per_hour` / `chat_rate_limit_per_hour` (0 = unlimited,
# the default) in `app/dependencies.py`. Module constants are exactly what made the old
# 5/hour cap unconfigurable and throttled the single-tenant operator paying their own bill.
LOGIN_IP = RateLimit(20, 60)
LOGIN_EMAIL = RateLimit(5, 900)  # 5 failures / 15 min → lockout window
REGISTER_IP = RateLimit(5, 3600)


@dataclass(frozen=True)
class RateResult:
    allowed: bool
    current: int
    ttl: int


async def check(redis, key: str, rule: RateLimit) -> RateResult:
    """Increment `key` and report whether it is within `rule`. TTL guaranteed."""
    current, ttl = await redis.eval(_LUA, 1, key, rule.limit, rule.window_seconds)
    return RateResult(allowed=current <= rule.limit, current=int(current), ttl=int(ttl))


def key_research(user_id) -> str:
    return f"rl:research:{user_id}"


def key_chat(user_id) -> str:
    return f"rl:chat:{user_id}"


def key_login_ip(ip: str) -> str:
    return f"rl:login:ip:{ip}"


def key_login_email(email: str) -> str:
    return f"rl:login:email:{email.lower()}"


def key_register_ip(ip: str) -> str:
    return f"rl:register:ip:{ip}"
