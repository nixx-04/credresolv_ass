from collections import defaultdict
from typing import Dict, List, Optional

from smartdialer.providers.base import TelecomProvider


class ProviderRegistry:
    def __init__(self, providers: Optional[List[TelecomProvider]] = None):
        self.providers: Dict[str, TelecomProvider] = {}
        self.metrics = defaultdict(lambda: {"success": 0, "failure": 0})

        for provider in providers or []:
            self.add_provider(provider)

    def add_provider(self, provider: TelecomProvider) -> None:
        self.providers[provider.name] = provider

    def get(self, name: str) -> Optional[TelecomProvider]:
        return self.providers.get(name)

    def all(self) -> List[TelecomProvider]:
        return list(self.providers.values())

    def record_success(self, provider_name: Optional[str]) -> None:
        if provider_name:
            self.metrics[provider_name]["success"] += 1

    def record_failure(self, provider_name: Optional[str]) -> None:
        if provider_name:
            self.metrics[provider_name]["failure"] += 1

    def error_rate(self, provider_name: str) -> float:
        metric = self.metrics[provider_name]
        total = metric["success"] + metric["failure"]
        if total == 0:
            return 0.0
        return metric["failure"] / total

    def choose_provider(self) -> TelecomProvider:
        if not self.providers:
            raise RuntimeError("No telecom providers registered")

        providers = list(self.providers.values())
        healthy = [p for p in providers if self.error_rate(p.name) < 0.5]

        candidates = healthy if healthy else providers
        return min(candidates, key=lambda p: self.error_rate(p.name))