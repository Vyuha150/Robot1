"""NotifierAdapter — extension point for SMS/print token delivery.

MockNotifierAdapter just logs what it would have sent. Real deployments
swap in an SMS gateway / receipt-printer adapter without touching queue_api.py.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class NotifierAdapter(ABC):
    @abstractmethod
    def send_token_sms(self, phone: str, token_code: str, department_name: str) -> bool: ...

    @abstractmethod
    def print_token(self, token_code: str, department_name: str, estimated_wait_min: float) -> bool: ...


class MockNotifierAdapter(NotifierAdapter):
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_token_sms(self, phone: str, token_code: str, department_name: str) -> bool:
        logger.info("[mock-sms] to=%s token=%s dept=%s", phone, token_code, department_name)
        self.sent.append({"type": "sms", "phone": phone, "token_code": token_code})
        return True

    def print_token(self, token_code: str, department_name: str, estimated_wait_min: float) -> bool:
        logger.info(
            "[mock-print] token=%s dept=%s eta_min=%s", token_code, department_name, estimated_wait_min
        )
        self.sent.append({"type": "print", "token_code": token_code})
        return True
