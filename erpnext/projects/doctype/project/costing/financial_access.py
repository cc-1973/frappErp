# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model import get_permitted_fields

# Project fields holding its cost, on permission level 2, and its billing and margin, on level 3.
# Billing sits with margin because cost and billed together give the margin away.
COST_FIELDS = (
	"estimated_costing",
	"total_costing_amount",
	"total_purchase_cost",
	"total_consumed_material_cost",
)
MARGIN_FIELDS = (
	"total_sales_amount",
	"total_billable_amount",
	"total_billed_amount",
	"gross_margin",
	"per_gross_margin",
)


def get_financial_access() -> frappe._dict:
	"""Whether the user may see a project's cost (`cost`) and its billing and margin (`margin`).

	Each holds when the user can read every Project field of that kind, so the Costing and Overview
	tabs follow the permission levels an admin grants on those fields, as the form and reports do.
	Administrator sees every field on the form.
	"""
	if frappe.session.user == "Administrator":
		return frappe._dict(cost=True, margin=True)
	readable = set(get_permitted_fields("Project", permission_type="read"))
	return frappe._dict(cost=readable.issuperset(COST_FIELDS), margin=readable.issuperset(MARGIN_FIELDS))


def check_financial_access(kind: str) -> None:
	"""Raise PermissionError unless the user may see the project figures of `kind`, "cost" or "margin"."""
	if not get_financial_access()[kind]:
		frappe.throw(_("Not permitted"), frappe.PermissionError)
