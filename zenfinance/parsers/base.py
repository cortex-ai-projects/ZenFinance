"""
ZenFinance — Base Parser contract.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

import pandas as pd

from zenfinance.models import TransactionDTO


class BaseParser(ABC):
    """All bank/app parsers implement this interface."""

    bank_name: str = "Unknown"

    @abstractmethod
    def parse(self, file_like, filename: str) -> List[TransactionDTO]:
        """
        Accept a file-like object (BytesIO / UploadedFile) and filename.
        Return a list of TransactionDTO objects.
        """
        ...

    def _safe_float(self, val) -> float:
        try:
            if pd.isna(val):
                return 0.0
        except Exception:
            pass
        try:
            return float(str(val).replace(",", "").strip())
        except (ValueError, TypeError):
            return 0.0

    def _safe_str(self, val) -> str:
        if val is None:
            return ""
        try:
            if pd.isna(val):
                return ""
        except Exception:
            pass
        return str(val).strip()
