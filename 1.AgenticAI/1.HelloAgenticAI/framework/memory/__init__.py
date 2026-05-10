"""Memory layer — Cosmos DB providers for sessions and trace events."""

from framework.memory.cosmos import (
    DEFAULT_DATABASE,
    SESSIONS_CONTAINER,
    TRACES_CONTAINER,
    CosmosProvider,
    CosmosSink,
)

__all__ = [
    "DEFAULT_DATABASE",
    "SESSIONS_CONTAINER",
    "TRACES_CONTAINER",
    "CosmosProvider",
    "CosmosSink",
]
