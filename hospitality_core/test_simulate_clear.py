import frappe

def run():
    print("Simulating UI clear of cover_image on Hotel Settings:")
    settings = frappe.get_single("Hotel Settings")
    old_cover = settings.cover_image
    print(f"Current cover_image: {old_cover}")

    # In UI, clicking Clear sets the field to None and saves the form
    settings.cover_image = None
    settings.save()
    frappe.db.commit()

    settings.reload()
    print(f"After save, cover_image: {settings.cover_image}")

    # Now simulate removing attachment if UI triggers remove_attachment_by_filename
    # Let's see what happens if someone deletes the File record or calls remove_attachment
    print("Testing if File deletion is attempted or what happens...")
    files = frappe.get_all("File", filters={"file_url": old_cover})
    print(f"File records found for {old_cover}: {files}")
    for f in files:
        file_doc = frappe.get_doc("File", f.name)
        try:
            file_doc.delete()
            print(f"Successfully deleted File {f.name}")
        except Exception as e:
            print(f"File delete failed with: {e}")

    frappe.db.rollback()
