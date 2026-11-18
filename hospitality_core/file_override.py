import frappe
from frappe.core.doctype.file.file import File

AUTO_CLEAR_DOCTYPES = {"Hotel Settings"}
ATTACH_TYPES = ("Attach", "Attach Image")


class HospitalityFile(File):
	def validate_not_referenced_in_attach_field(self):
		"""For Hotel Settings, deleting an attachment clears any Attach field
		(parent or child row) pointing at it instead of blocking the delete."""
		if self.attached_to_doctype not in AUTO_CLEAR_DOCTYPES or not self.file_url:
			return super().validate_not_referenced_in_attach_field()

		# Another File record still backs this URL -> nothing to clear
		if frappe.get_all("File", filters={"file_url": self.file_url, "name": ["!=", self.name]}, limit=1):
			return

		try:
			ref_doc = frappe.get_doc(self.attached_to_doctype, self.attached_to_name)
		except frappe.DoesNotExistError:
			return

		changed = False
		for df in ref_doc.meta.get("fields", {"fieldtype": ["in", ATTACH_TYPES]}):
			if ref_doc.get(df.fieldname) == self.file_url:
				ref_doc.set(df.fieldname, None)
				changed = True

		# Child rows (e.g. property gallery) can't exist without their image -> drop the row
		for tf in ref_doc.meta.get_table_fields():
			rows = ref_doc.get(tf.fieldname) or []
			keep = [
				r for r in rows
				if not any(r.get(df.fieldname) == self.file_url
					for df in r.meta.get("fields", {"fieldtype": ["in", ATTACH_TYPES]}))
			]
			if len(keep) != len(rows):
				for i, r in enumerate(keep, 1):
					r.idx = i
				ref_doc.set(tf.fieldname, keep)
				changed = True

		if changed:
			ref_doc.flags.ignore_permissions = True
			ref_doc.save()
