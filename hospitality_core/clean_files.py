import frappe


def run(dry_run=1, module="Hospitality Core"):
    """Broken /files/ links saaf kare. dry_run=1 hoy to sirf report."""
    dry_run = int(dry_run)

    def missing(url):
        return (
            isinstance(url, str)
            and url.startswith(("/files/", "/private/files/"))
            and not frappe.db.exists("File", {"file_url": url})
        )

    found = []

    doctypes = frappe.get_all(
        "DocType",
        filters={"module": module},
        fields=["name", "issingle", "istable"],
    )

    for dt in doctypes:
        meta = frappe.get_meta(dt.name)
        for df in meta.fields:
            if df.fieldtype not in ("Attach", "Attach Image"):
                continue
            fn = df.fieldname

            if dt.issingle:
                res = frappe.db.sql(
                    "select value from `tabSingles` where doctype=%s and field=%s",
                    (dt.name, fn),
                )
                url = res[0][0] if res else None
                if missing(url):
                    found.append((dt.name, fn, "single", url))
                    if not dry_run:
                        frappe.db.set_single_value(dt.name, fn, None)
            else:
                rows = frappe.db.sql(
                    f"select name, `{fn}` from `tab{dt.name}` where `{fn}` like %s",
                    ("%/files/%",),
                )
                for name, url in rows:
                    if not missing(url):
                        continue
                    action = "row delete" if dt.istable else "field clear"
                    found.append((dt.name, fn, f"{action}: {name}", url))
                    if not dry_run:
                        if dt.istable:
                            frappe.db.delete(dt.name, {"name": name})
                        else:
                            frappe.db.set_value(dt.name, name, fn, None)

    for f in found:
        print(f)
    print(f"\nTotal broken: {len(found)} | dry_run={dry_run}")

    if not dry_run:
        frappe.db.commit()
        frappe.clear_cache()
