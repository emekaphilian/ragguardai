from dataclasses import dataclass

@dataclass
class RuntimeMetrics:
    queries: int = 0
    failures: int = 0
    repairs: int = 0
    successful_repairs: int = 0
    total_repair_time_ms: float = 0.0

    @property
    def failure_rate(self):
        return self.failures / self.queries if self.queries else 0.0

    @property
    def repair_success_rate(self):
        return self.successful_repairs / self.repairs if self.repairs else 0.0
