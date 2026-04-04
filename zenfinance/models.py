"""
ZenFinance — Core Data Models
"""
from __future__ import annotations
import uuid
import hashlib
from typing import Literal, Optional
from datetime import date


# Canonical column order used across all DataFrames / CSVs
TRANSACTION_COLUMNS = [
    "id",
    "hash",
    "date",
    "amount",
    "txn_type",
    "bank_name",
    "bank_description",
    "details",
    "payment_method",
    "category",
    "sub_category",
    "tags",
    "transaction_id",
    "utr_number",
    "reference_number",
    "audit_status",
    "duplicate_transaction_id",
    "system_comment",
    "source_file",
]

AuditStatus = Literal["Pending", "Audited", "Flagged", "Duplicate"]
TxnType     = Literal["CREDIT", "DEBIT"]


class TransactionDTO:
    """
    Unified data-transfer object for any finance transaction.
    Builds on the existing Colab model, adding category + dedup hash.
    """

    def __init__(
        self,
        id: Optional[uuid.UUID] = None,
        date: Optional[date] = None,
        amount: float = 0.0,
        bank_description: str = "",
        details: Optional[str] = None,
        txn_type: TxnType = "DEBIT",
        bank_name: str = "Unknown",
        payment_method: Optional[str] = None,
        category: Optional[str] = None,
        sub_category: Optional[str] = None,
        tags: Optional[str] = None,
        transaction_id: Optional[str] = None,
        utr_number: Optional[str] = None,
        audit_status: AuditStatus = "Pending",
        duplicate_transaction_id: Optional[uuid.UUID] = None,
        reference_number: Optional[str] = None,
        system_comment: Optional[str] = None,
        source_file: Optional[str] = None,
        hash: Optional[str] = None,
    ):
        self.id = id or uuid.uuid4()
        self.date = date
        self.amount = float(amount) if amount is not None else 0.0
        self.bank_description = bank_description or ""
        self.details = details
        self.txn_type = txn_type
        self.bank_name = bank_name
        self.payment_method = payment_method
        self.category = category
        self.sub_category = sub_category
        self.tags = tags
        self.transaction_id = transaction_id
        self.utr_number = utr_number
        self.audit_status = audit_status
        self.duplicate_transaction_id = duplicate_transaction_id
        self.reference_number = reference_number
        self.system_comment = system_comment
        self.source_file = source_file
        # Build dedup hash if not provided
        self.hash = hash or self._build_hash()

    def _build_hash(self) -> str:
        """MD5 of Date + Amount + Description — used for deduplication."""
        raw = f"{self.date}|{round(self.amount, 2)}|{(self.bank_description or '').strip().lower()}"
        return hashlib.md5(raw.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "hash": self.hash,
            "date": str(self.date) if self.date else None,
            "amount": self.amount,
            "txn_type": self.txn_type,
            "bank_name": self.bank_name,
            "bank_description": self.bank_description,
            "details": self.details,
            "payment_method": self.payment_method,
            "category": self.category,
            "sub_category": self.sub_category,
            "tags": self.tags,
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "utr_number": str(self.utr_number) if self.utr_number else None,
            "reference_number": str(self.reference_number) if self.reference_number else None,
            "audit_status": self.audit_status,
            "duplicate_transaction_id": str(self.duplicate_transaction_id) if self.duplicate_transaction_id else None,
            "system_comment": self.system_comment,
            "source_file": self.source_file,
        }

    def __repr__(self):
        return (
            f"TransactionDTO(id={self.id!r}, date={self.date!r}, "
            f"amount={self.amount!r}, txn_type={self.txn_type!r}, "
            f"bank_name={self.bank_name!r}, category={self.category!r})"
        )

    def __eq__(self, other):
        return isinstance(other, TransactionDTO) and self.hash == other.hash

    def __hash__(self):
        return hash(self.hash)
