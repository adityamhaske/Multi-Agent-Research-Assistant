"""
Merging a settings request into a user's stored preferences — one home, both hosts.

Preferences arrive a section at a time, so a request carries only the fields the section it
came from owns and a naive overwrite would blank every other section. Both hosts therefore
merge rather than replace, and that rule already had two copies before this module existed.

`prompt_overrides` needs a second level of the same care, and it is the reason this is a
function rather than a `dict.update` at each call site. It is a map, so a top-level merge
would replace the whole map: a request setting one role's prompt would silently drop the
other four. So it merges per role, and `null` deletes that role's entry rather than storing
a null — the difference between "reset this one" and "I sent you nothing about it", which
the top-level merge cannot express on its own.

Nothing here validates. `app.schemas.auth.UserPreferences` does that, on both hosts, before
anything reaches this function.
"""

from __future__ import annotations

from typing import Any

#: The one preference whose value is a map and therefore cannot be merged at the top level.
#: A second such preference would join it here rather than growing a branch at a call site.
_NESTED_MAP_PREFERENCES = ("prompt_overrides",)


def merge_preferences(stored: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    """The stored preferences with `incoming` applied. Neither argument is mutated.

    `incoming` is expected to carry only the fields the request actually set — on the server
    that is `model_dump(exclude_unset=True)`, so a field the client never mentioned is absent
    here rather than present as `None`, and absent means "leave it alone".
    """
    merged = dict(stored or {})
    for key, value in incoming.items():
        if key not in _NESTED_MAP_PREFERENCES:
            merged[key] = value
            continue
        if value is None:
            # The whole map reset: the user cleared every override at once.
            merged.pop(key, None)
            continue
        nested = dict(merged.get(key) or {})
        for inner_key, inner_value in value.items():
            if inner_value is None:
                nested.pop(inner_key, None)  # reset this role to its shipped prompt
            else:
                nested[inner_key] = inner_value
        # An empty map is the same state as no map, and storing `{}` would leave a user who
        # reset their last override looking different from one who never set any.
        if nested:
            merged[key] = nested
        else:
            merged.pop(key, None)
    return merged
