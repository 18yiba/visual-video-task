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

    @classmethod
    def list_hardware_devices(cls) -> list[str]:
        """Real acquisition backends only (excludes the internal dummy backend)."""
        hidden_backends = {"dummy", "brainco_lsl", "brainco_bcigo"}
        return [name for name in cls.list_devices() if name not in hidden_backends]


def register_default_acquirers() -> None:
    """Register all built-in backends once."""

    if AcquirerFactory._registry:
        return

    from acquisition.brainco_acquirer import BrainCoAcquirer
    from acquisition.dummy_acquirer import DummyAcquirer #added
    from acquisition.external_recorder_acquirer import ExternalRecorderAcquirer
    from acquisition.lsl_acquirer import LSLAcquirer
    from acquisition.neuracle_acquirer import NeuracleAcquirer

    AcquirerFactory.register("brainco", BrainCoAcquirer)
    AcquirerFactory.register("brainco_bcigo", ExternalRecorderAcquirer)
    AcquirerFactory.register("brainco_lsl", LSLAcquirer)
    AcquirerFactory.register("dummy", DummyAcquirer) #added
    AcquirerFactory.register("neuracle", NeuracleAcquirer)
