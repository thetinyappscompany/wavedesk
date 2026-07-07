import frappe
from frappe import _
from frappe.model.document import Document


class WDWalletTransaction(Document):
    """APPEND-ONLY ledger row (root non-negotiable #2). No updates, no deletes, ever.

    Corrections are new `adjustment`/`refund` rows via wavedesk.wallet — the audit
    trail stays intact.
    """

    def validate(self) -> None:
        if not self.is_new():
            frappe.throw(
                _("WD Wallet Transaction is append-only; ledger rows cannot be modified"),
                frappe.ValidationError,
            )
        if not self.idempotency_key:
            frappe.throw(_("idempotency_key is mandatory"), frappe.ValidationError)

    def on_trash(self) -> None:
        frappe.throw(
            _("WD Wallet Transaction is append-only; ledger rows cannot be deleted"),
            frappe.ValidationError,
        )
