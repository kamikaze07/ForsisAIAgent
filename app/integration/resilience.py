"""
Resilience Handler: Circuit Breaker, Retry Policy, Timeout, and Fallback handling.
"""

import time
from typing import Callable, Any, Dict, Optional, List


class CircuitBreakerOpenException(Exception):
    """Raised when circuit breaker is in OPEN state."""
    pass


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_timeout_s: float = 10.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"

    def allow_execution(self) -> bool:
        if self.state == "CLOSED":
            return True

        if self.state == "OPEN":
            if self.last_failure_time and (time.time() - self.last_failure_time) > self.recovery_timeout_s:
                self.state = "HALF_OPEN"
                return True
            return False

        if self.state == "HALF_OPEN":
            return True

        return True


class ResilienceHandler:
    def __init__(
        self,
        max_retries: int = 2,
        retry_delay_s: float = 0.1,
        timeout_s: float = 5.0,
        circuit_breaker: Optional[CircuitBreaker] = None
    ):
        self.max_retries = max_retries
        self.retry_delay_s = retry_delay_s
        self.timeout_s = timeout_s
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    def execute_with_resilience(
        self,
        func: Callable[[], Dict[str, Any]],
        fallback_func: Optional[Callable[[], Dict[str, Any]]] = None
    ) -> Tuple_Resilience_Result:
        """
        Execute function wrapped with circuit breaker, retries, and fallback.
        """
        if not self.circuit_breaker.allow_execution():
            if fallback_func:
                return func_fallback_wrapper(fallback_func, "Circuit breaker OPEN: returning fallback degradation.")
            raise CircuitBreakerOpenException("Circuit breaker is OPEN. Target system unavailable.")

        retries_done: List[Dict[str, Any]] = []
        last_error = None

        for attempt in range(self.max_retries + 1):
            t_start = time.time()
            try:
                result = func()
                self.circuit_breaker.record_success()
                return ResilienceResult(
                    success=True,
                    data=result,
                    retries=retries_done,
                    error=None
                )
            except Exception as ex:
                elapsed = (time.time() - t_start) * 1000.0
                last_error = str(ex)
                retries_done.append({
                    "attempt": attempt + 1,
                    "error": last_error,
                    "duration_ms": elapsed
                })
                self.circuit_breaker.record_failure()
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_s)

        if fallback_func:
            return func_fallback_wrapper(fallback_func, f"Execution failed after {self.max_retries} retries: {last_error}")

        return ResilienceResult(
            success=False,
            data={},
            retries=retries_done,
            error=last_error
        )


class ResilienceResult:
    def __init__(self, success: bool, data: Dict[str, Any], retries: List[Dict[str, Any]], error: Optional[str]):
        self.success = success
        self.data = data
        self.retries = retries
        self.error = error


def func_fallback_wrapper(fallback_fn: Callable[[], Dict[str, Any]], message: str) -> ResilienceResult:
    try:
        data = fallback_fn()
        data["_degraded"] = True
        data["_degradation_reason"] = message
        return ResilienceResult(success=True, data=data, retries=[], error=message)
    except Exception as ex:
        return ResilienceResult(success=False, data={}, retries=[], error=f"{message} | Fallback error: {str(ex)}")
