import frappe
from frappe.permissions import get_doctypes_with_custom_docperms

COST_LEVEL = 2
MARGIN_LEVEL = 3
DOCTYPES = ("Project", "Task")
# Estimated Cost moved to the cost level; the roles that could edit it keep that right.
EDITABLE_DOCTYPE = "Project"


def execute():
	"""Give sites that customised Project or Task permissions the cost and margin levels, as the
	standard rules do: every role that reads the doctype may read both, and on Project every role
	that edits it may edit Estimated Cost. Custom rules replace the standard ones, so without this
	nobody would see those fields. A level the site already uses for its own fields keeps its rules,
	so its fields are not opened to more roles."""
	customised = set(get_doctypes_with_custom_docperms())
	for doctype in DOCTYPES:
		if doctype not in customised:
			continue
		rights = level_zero_rights(doctype)
		for level in unused_levels(doctype):
			for role, write in rights.items():
				editable = doctype == EDITABLE_DOCTYPE and level == COST_LEVEL
				add_rule(doctype, role, level, write if editable else 0)
		frappe.clear_cache(doctype=doctype)


def unused_levels(doctype: str) -> list[int]:
	used = set(frappe.get_all("Custom DocPerm", filters={"parent": doctype}, pluck="permlevel"))
	return [level for level in (COST_LEVEL, MARGIN_LEVEL) if level not in used]


def level_zero_rights(doctype: str) -> dict[str, int]:
	"""Each role that reads `doctype`, and whether it may also edit it."""
	rules = frappe.get_all(
		"Custom DocPerm",
		filters={"parent": doctype, "permlevel": 0, "read": 1},
		fields=["role", "write"],
	)
	rights = {}
	for rule in rules:
		rights[rule.role] = max(rights.get(rule.role, 0), rule.write)
	return rights


def add_rule(doctype: str, role: str, level: int, write: int) -> None:
	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": role,
			"permlevel": level,
			"read": 1,
			"report": 1,
			"write": write,
		}
	).insert(ignore_permissions=True)
