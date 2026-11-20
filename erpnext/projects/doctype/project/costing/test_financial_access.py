# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.client import get as get_document
from frappe.core.doctype.user_permission.test_user_permission import create_user
from frappe.model.document import Document
from frappe.permissions import setup_custom_perms

from erpnext.patches.v16_0.add_project_financial_perm_levels import execute as add_financial_levels
from erpnext.projects.doctype.project.costing.accounts import get_ledger_entries, get_project_accounts
from erpnext.projects.doctype.project.costing.project_budgets import get_project_budgets
from erpnext.projects.doctype.project.costing.project_costing import (
	get_project_costing,
	get_project_invoices,
)
from erpnext.projects.doctype.project.project_overview import get_project_overview
from erpnext.projects.doctype.project.test_project import make_project
from erpnext.tests.utils import ERPNextTestSuite

COST_LEVEL = 2
MARGIN_LEVEL = 3
VIEWER = "financial-viewer@example.com"
LEDGER_VIEWER = "financial-ledger-viewer@example.com"
OTHER_PROJECT_VIEWER = "financial-other-project@example.com"
SHARED_VIEWER = "financial-shared-viewer@example.com"


class TestFinancialAccess(ERPNextTestSuite):
	"""A number field the user may not read comes back from the API as 0, not as its value."""

	def setUp(self) -> None:
		for doctype in ("Project", "Task"):
			self.use_shipped_rules(doctype)
		self.project = new_project()
		self.project.db_set({"customer": "_Test Customer", "estimated_costing": 5000, "gross_margin": 700})
		self.viewer = create_user(VIEWER, "Projects User").name

	def test_projects_roles_see_financials_by_default(self) -> None:
		"""The shipped rules let the roles that read a Project see its cost and margin, as before. A user
		who reads the project only because it is shared with them sees neither."""
		costing = self.as_viewer(get_project_costing, self.project.name)
		overview = self.as_viewer(get_project_overview, self.project.name)
		project = self.as_viewer(get_document, "Project", self.project.name)

		self.assertEqual(costing["errors"], {})
		self.assertIn("margin", costing["summary"])
		self.assertIsNotNone(costing["billing"])
		self.assertIsNotNone(overview["profitability"])
		self.assertEqual((project.estimated_costing, project.gross_margin), (5000, 700))

		shared_viewer = create_user(SHARED_VIEWER, "Sales User").name
		frappe.share.add("Project", self.project.name, shared_viewer, read=1)
		shared = self.as_user(shared_viewer, get_document, "Project", self.project.name)
		self.assertEqual(shared.project_name, self.project.project_name)
		self.assertEqual((shared.estimated_costing, shared.gross_margin), (0, 0))

	def test_cost_without_margin(self) -> None:
		"""Without the margin level, cost shows while billing and margin are left out everywhere."""
		self.remove_rules("Project", "Projects User", MARGIN_LEVEL)
		self.remove_rules("Task", "Projects User", MARGIN_LEVEL)
		task = self.task_with_totals()
		ledger_viewer = create_user(LEDGER_VIEWER, "Projects User", "Accounts User").name

		costing = self.as_viewer(get_project_costing, self.project.name)
		self.assertIn("cost", costing["summary"])
		self.assertFalse(set(costing["summary"]).intersection({"billed", "margin", "contract"}))
		self.assertIsNone(costing["billing"])
		overview = self.as_viewer(get_project_overview, self.project.name)
		self.assertEqual((overview["profitability"], overview["unbilled"]), (None, None))

		project = self.as_viewer(get_document, "Project", self.project.name)
		task = self.as_viewer(get_document, "Task", task.name)
		self.assertEqual((project.estimated_costing, project.gross_margin), (5000, 0))
		self.assertEqual((task.total_costing_amount, task.total_billing_amount), (300, 0))

		self.assertRaises(frappe.PermissionError, self.as_viewer, get_project_invoices, self.project.name)
		for root_type in ("Income", None):
			with self.assertRaises(frappe.PermissionError):
				self.as_user(ledger_viewer, get_ledger_entries, self.project.name, root_type)

	def test_neither_level(self) -> None:
		"""Without either level, progress still shows while every financial figure and request is held
		back."""
		for doctype in ("Project", "Task"):
			self.remove_rules(doctype, "Projects User", COST_LEVEL, MARGIN_LEVEL)
		task = self.task_with_totals()
		ledger_viewer = create_user(LEDGER_VIEWER, "Projects User", "Accounts User").name

		overview = self.as_viewer(get_project_overview, self.project.name)
		self.assertIsNotNone(overview["summary"])
		self.assertIsNone(overview["profitability"])

		project = self.as_viewer(get_document, "Project", self.project.name)
		task = self.as_viewer(get_document, "Task", task.name)
		self.assertEqual(project.project_name, self.project.project_name)
		self.assertEqual((project.estimated_costing, project.gross_margin), (0, 0))
		self.assertEqual((task.total_costing_amount, task.total_billing_amount), (0, 0))

		for method in (get_project_costing, get_project_budgets):
			self.assertRaises(frappe.PermissionError, self.as_viewer, method, self.project.name)
		for method in (get_project_accounts, get_ledger_entries):
			self.assertRaises(frappe.PermissionError, self.as_user, ledger_viewer, method, self.project.name)

	def test_financial_access_keeps_to_readable_projects(self) -> None:
		"""The levels show figures only on Projects the user may read."""
		viewer = create_user(OTHER_PROJECT_VIEWER, "Projects User").name
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": viewer,
				"allow": "Project",
				"for_value": new_project().name,
			}
		).insert()

		self.assertRaises(
			frappe.PermissionError, self.as_user, viewer, get_project_costing, self.project.name
		)

	def test_patch_adds_the_levels_on_customised_sites(self) -> None:
		"""On a site whose rules are custom and predate the levels, the patch grants both to every role
		that reads the doctype, with edit rights on Project's cost level for the roles that edit it. A
		level the site already uses for its own fields keeps its rules."""
		for doctype in ("Project", "Task"):
			self.customise(doctype)
			frappe.db.delete(
				"Custom DocPerm", {"parent": doctype, "permlevel": ["in", [COST_LEVEL, MARGIN_LEVEL]]}
			)
		add_financial_rule("Task", "Projects User", MARGIN_LEVEL)

		add_financial_levels()

		self.assertEqual(
			self.custom_rules("Project", COST_LEVEL), [("Projects Manager", 1), ("Projects User", 1)]
		)
		self.assertEqual(
			self.custom_rules("Project", MARGIN_LEVEL), [("Projects Manager", 0), ("Projects User", 0)]
		)
		self.assertEqual(self.custom_rules("Task", COST_LEVEL), [("HR Manager", 0), ("Projects User", 0)])
		self.assertEqual(self.custom_rules("Task", MARGIN_LEVEL), [("Projects User", 0)])

	def task_with_totals(self) -> Document:
		task = frappe.get_doc(
			{"doctype": "Task", "subject": "_Test Financials Task", "project": self.project.name}
		).insert()
		task.db_set({"total_costing_amount": 300, "total_billing_amount": 400})
		return task

	def as_viewer(self, function, *args):
		return self.as_user(self.viewer, function, *args)

	def as_user(self, user: str, function, *args):
		frappe.set_user(user)
		try:
			return function(*args)
		finally:
			frappe.set_user("Administrator")

	def use_shipped_rules(self, doctype: str) -> None:
		"""Start from the rules the doctype ships with, whatever the site customised."""
		frappe.db.delete("Custom DocPerm", {"parent": doctype})
		frappe.clear_cache(doctype=doctype)
		self.addCleanup(frappe.clear_cache, doctype=doctype)

	def customise(self, doctype: str) -> None:
		setup_custom_perms(doctype)
		self.addCleanup(frappe.clear_cache, doctype=doctype)

	def remove_rules(self, doctype: str, role: str, *levels: int) -> None:
		self.customise(doctype)
		frappe.db.delete(
			"Custom DocPerm", {"parent": doctype, "role": role, "permlevel": ["in", list(levels)]}
		)
		frappe.clear_cache(doctype=doctype)

	def custom_rules(self, doctype: str, level: int) -> list[tuple[str, int]]:
		rules = frappe.get_all(
			"Custom DocPerm",
			filters={"parent": doctype, "permlevel": level},
			fields=["role", "write"],
			order_by="role",
		)
		return [(rule.role, rule.write) for rule in rules]


def grant_financial_levels(doctype: str, role: str) -> None:
	"""Let `role` read the cost and margin fields of `doctype`, as an admin would in Role Permission
	Manager. The caller clears the doctype's cache when done."""
	setup_custom_perms(doctype)
	for level in (COST_LEVEL, MARGIN_LEVEL):
		add_financial_rule(doctype, role, level)
	frappe.clear_cache(doctype=doctype)


def add_financial_rule(doctype: str, role: str, level: int) -> None:
	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": role,
			"permlevel": level,
			"read": 1,
		}
	).insert()


def new_project() -> Document:
	return make_project({"project_name": f"_Test Financials {frappe.generate_hash(length=6)}"})
