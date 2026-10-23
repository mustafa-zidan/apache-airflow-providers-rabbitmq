"""
Airflow 2.x / 3.x compatibility layer.

Every import that moved between Airflow versions is resolved here once, so the
hooks, sensors and triggers import from a single place. ``Context`` is only
available to type checkers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

try:
    from airflow.sdk.bases.hook import BaseHook  # Airflow 3.x
except ImportError:
    from airflow.hooks.base import BaseHook  # type: ignore[attr-defined, no-redef]

try:
    from airflow.sdk.bases.sensor import (  # Airflow 3.x
        BaseSensorOperator,
        PokeReturnValue,
    )
except ImportError:
    from airflow.sensors.base import (  # type: ignore[no-redef]
        BaseSensorOperator,
        PokeReturnValue,
    )

# airflow.utils.module_loading is gone in Airflow 3.3; Airflow 3 ships common.compat.
try:
    from airflow.providers.common.compat.module_loading import import_string
except ImportError:
    from airflow.utils.module_loading import import_string

# BaseEventTrigger is Airflow 3 only; on 2.x the trigger works for deferral only.
try:
    from airflow.triggers.base import BaseEventTrigger
except ImportError:
    from airflow.triggers.base import BaseTrigger

    BaseEventTrigger = BaseTrigger  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    try:
        from airflow.sdk.definitions.context import Context  # Airflow 3.x
    except ImportError:
        from airflow.utils.context import Context  # type: ignore[attr-defined,no-redef]

__all__ = [
    "BaseEventTrigger",
    "BaseHook",
    "BaseSensorOperator",
    "Context",
    "PokeReturnValue",
    "import_string",
    "unwrap_serialized",
]

# Airflow < 3.3.1 can hand AssetWatcher triggers their kwargs still wrapped in
# BaseSerialization markers, stored under the stringified enum names
# (apache/airflow#65973). Both spellings are unwrapped.
_TYPE_KEYS = ("__type", "Encoding.TYPE")
_VAR_KEYS = ("__var", "Encoding.VAR")
_CONTAINERS: dict[str, Callable[[Any], Any]] = {
    "dict": dict,
    "list": list,
    "tuple": tuple,
    "set": set,
    "frozenset": frozenset,
}


def unwrap_serialized(value: Any) -> Any:
    """Undo BaseSerialization wrapping of containers; leave other values as they are."""
    if isinstance(value, dict):
        type_key = next((k for k in _TYPE_KEYS if k in value), None)
        var_key = next((k for k in _VAR_KEYS if k in value), None)
        if type_key and var_key and len(value) == 2 and value[type_key] in _CONTAINERS:
            return _CONTAINERS[value[type_key]](unwrap_serialized(value[var_key]))
        return {k: unwrap_serialized(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return type(value)(unwrap_serialized(v) for v in value)
    return value
