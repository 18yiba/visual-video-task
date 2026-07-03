"""Registry-based factory for acquisition backends."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from acquisition.base import AbstractAcquirer

LOGGER = logging.getLogger(__name__)

AcquirerBuilder = Callable[..., AbstractAcquirer]


class AcquirerFactory:
    """Creates acquisition backends by name."""

    _registry: dict[str, AcquirerBuilder] = {}

    @classmethod
    def register(cls, name: str, builder: AcquirerBuilder) -> None:
        cls._registry[name] = builder
        LOGGER.debug("Registered acquirer '%s'", name)

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> AbstractAcquirer:
        if name not in cls._registry:
            available = ", ".join(sorted(cls._registry))
            raise ValueError(f"Unknown device '{name}'. Available devices: {available}")
        return cls._registry[name](**kwargs)

    @classmethod
    def list_devices(cls) -> list[str]:
        return sorted(cls._registry)


def register_default_acquirers() -> None:
    """Register all built-in backends once."""

    if AcquirerFactory._registry:
        return

    from acquisition.brainco_acquirer import BrainCoAcquirer
    from acquisition.dummy_acquirer import DummyAcquirer #added
    from acquisition.neuracle_acquirer import NeuracleAcquirer

    AcquirerFactory.register("brainco", BrainCoAcquirer)
    AcquirerFactory.register("dummy", DummyAcquirer) #added
    AcquirerFactory.register("neuracle", NeuracleAcquirer)
