import frappe

def run():
    doc = frappe.get_single('Hotel Settings')
    print('=== Hotel Settings ===')
    print('cover_image:', doc.cover_image)
    print('hotel_logo:', doc.hotel_logo)
    print('property_images count:', len(doc.property_images))
    for row in doc.property_images:
        print('  row:', row.name, 'image:', row.image, 'primary:', row.is_primary_image)

    if doc.cover_image:
        files = frappe.get_all('File', filters={'file_url': doc.cover_image}, fields=['name', 'file_name', 'file_url', 'attached_to_doctype', 'attached_to_name', 'attached_to_field'])
        print('=== File records for cover_image ===')
        for f in files:
            print(' ', f)
