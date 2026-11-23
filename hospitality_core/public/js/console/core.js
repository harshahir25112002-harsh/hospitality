/**
 * Front Desk Console - core helpers (included into the page script via include directive).
 */
const FD = {
    STATUS: {
        "Available": { cls: "available", label: __("Available") },
        "Reserved": { cls: "reserved", label: __("Reserved") },
        "Occupied": { cls: "occupied", label: __("Occupied") },
        "Dirty": { cls: "dirty", label: __("Dirty") },
        "Out of Order": { cls: "ooo", label: __("Out of Order") },
    },
    RES_STATUS: {
        "Reserved": "blue", "Checked In": "green", "Checked Out": "gray", "Cancelled": "red",
    },

    icon(name, size = "sm") {
        return frappe.utils.icon(name, size);
    },
    esc(v) {
        return frappe.utils.escape_html(v === null || v === undefined ? "" : String(v));
    },
    money(v) {
        return format_currency(v || 0, frappe.boot.sysdefaults.currency);
    },
    date(v) {
        return v ? frappe.datetime.str_to_user(v) : "—";
    },
    pill(status) {
        const color = FD.RES_STATUS[status] || "gray";
        return `<span class="indicator-pill ${color}">${FD.esc(__(status))}</span>`;
    },
    room_pill(status) {
        const s = FD.STATUS[status] || { cls: "available", label: status };
        return `<span class="fd-status-chip fd-st-${s.cls}">${FD.esc(s.label)}</span>`;
    },
    empty(msg, icon = "inbox") {
        return `<div class="fd-empty">${FD.icon(icon, "lg")}<div>${FD.esc(msg)}</div></div>`;
    },
    skeleton(n = 8) {
        return `<div class="fd-room-grid">${Array.from({ length: n }).map(() => `<div class="fd-skel"></div>`).join("")}</div>`;
    },

    /**
     * frappe.call wrapper: returns a Promise, optionally locks a button / dialog primary
     * button against double clicks while the request is in flight.
     */
    call(method, args = {}, opts = {}) {
        const $btn = opts.btn ? $(opts.btn) : null;
        if ($btn) {
            if ($btn.prop("disabled")) return Promise.reject("busy");
            $btn.prop("disabled", true).addClass("fd-busy");
        }
        return new Promise((resolve, reject) => {
            frappe.call({
                method,
                args,
                freeze: !!opts.freeze,
                freeze_message: opts.freeze_message,
                callback: (r) => (r.exc ? reject(r) : resolve(r.message)),
                error: (r) => reject(r),
                always: () => $btn && $btn.prop("disabled", false).removeClass("fd-busy"),
            });
        });
    },

    /** dialog whose primary action is guarded against double submit */
    dialog(opts) {
        const action = opts.primary_action;
        const d = new frappe.ui.Dialog(Object.assign({}, opts, {
            primary_action(values) {
                if (d.__busy) return;
                d.__busy = true;
                d.get_primary_btn().prop("disabled", true);
                Promise.resolve(action(values, d))
                    .catch(() => { /* server error already shown by frappe */ })
                    .finally(() => {
                        d.__busy = false;
                        d.get_primary_btn().prop("disabled", false);
                    });
            },
        }));
        if (!action) delete d.primary_action;
        d.$wrapper.addClass("fd-dialog");
        return d;
    },

    kv(rows) {
        return `<div class="fd-kv">${rows.filter(r => r && r[1] !== undefined && r[1] !== null && r[1] !== "")
            .map(([k, v, raw]) => `<div class="fd-kv-k">${FD.esc(k)}</div><div class="fd-kv-v">${raw ? v : FD.esc(v)}</div>`).join("")}</div>`;
    },
};

// ==========================================
// POPUP MODE: keep every create / open action inside the console
// ==========================================
function fd_on_console() {
    const route = frappe.get_route() || [];
    return route.includes("front-desk-console") || route.includes("front_desk_console");
}

// Read-only popup preview of any document (replaces navigating to its form)
function fd_open_doc_popup(doctype, name) {
    frappe.model.with_doctype(doctype, () => {
        frappe.call({
            method: "frappe.client.get",
            args: { doctype: doctype, name: name },
            freeze: true,
            freeze_message: __("Loading {0}...", [name]),
            callback: (r) => {
                const doc = r.message;
                if (!doc) {
                    frappe.msgprint({ title: __("Not Found"), message: __("Could not load {0} {1}", [doctype, name]), indicator: "red" });
                    return;
                }
                const meta = frappe.get_meta(doctype);
                const skip = ["Section Break", "Column Break", "Tab Break", "HTML", "Button", "Table", "Table MultiSelect", "Fold", "Heading", "Attach Image", "Text Editor", "Code", "Password"];
                let rows = "";
                (meta.fields || []).forEach((df) => {
                    if (skip.includes(df.fieldtype) || df.hidden) return;
                    const v = doc[df.fieldname];
                    if (v === undefined || v === null || v === "" || (v === 0 && df.fieldtype === "Check")) return;
                    rows += `<tr><td class="text-muted" style="width:40%">${FD.esc(__(df.label || df.fieldname))}</td><td>${frappe.format(v, df, { inline: true }, doc)}</td></tr>`;
                });
                (meta.fields || []).filter(df => df.fieldtype === "Table" && (doc[df.fieldname] || []).length).forEach((df) => {
                    const cm = frappe.get_meta(df.options);
                    const cols = (cm ? cm.fields : []).filter(f => f.in_list_view).slice(0, 5);
                    if (!cols.length) return;
                    rows += `<tr><td colspan="2"><b>${FD.esc(__(df.label))}</b><table class="table table-sm table-bordered mt-1 mb-0"><thead><tr>${cols.map(c => `<th>${FD.esc(__(c.label))}</th>`).join("")}</tr></thead><tbody>${doc[df.fieldname].map(row => `<tr>${cols.map(c => `<td>${frappe.format(row[c.fieldname], c, { inline: true }, row)}</td>`).join("")}</tr>`).join("")}</tbody></table></td></tr>`;
                });
                const bodyHtml = `<div style="max-height:65vh;overflow:auto"><table class="table table-sm">${rows || `<tr><td class="text-muted">${__("No details")}</td></tr>`}</table></div>`;
                const d = new frappe.ui.Dialog({
                    title: `${__(doctype)}: ${doc.name}`,
                    size: "large",
                    fields: [{ fieldtype: "HTML", fieldname: "body", options: bodyHtml }],
                });
                d.show();
                if (d.get_field("body") && d.get_field("body").$wrapper) {
                    d.get_field("body").$wrapper.html(bodyHtml);
                }
                if (frappe.model.can_print(doctype)) {
                    d.set_primary_action(__("Print"), () => fd_open_print_popup(doctype, doc.name));
                }
                d.$wrapper.addClass("fd-dialog");
            },
            error: () => {
                frappe.msgprint({ title: __("Error"), message: __("Failed to fetch {0} {1}", [doctype, name]), indicator: "red" });
            }
        });
    });
}

// Print view in a popup iframe instead of a new tab
function fd_open_print_popup(doctype, name) {
    const src = `/printview?doctype=${encodeURIComponent(doctype)}&name=${encodeURIComponent(name)}&trigger_print=0&no_letterhead=0`;
    const d = new frappe.ui.Dialog({ title: __("Print: {0}", [name]), size: "extra-large", fields: [{ fieldtype: "HTML", fieldname: "body" }] });
    d.fields_dict.body.$wrapper.html(`<iframe class="fd-print-frame" src="${src}" style="width:100%;height:70vh;border:0;background:#fff;border-radius:8px"></iframe>`);
    d.set_primary_action(__("Print"), () => {
        const fr = d.$wrapper.find(".fd-print-frame")[0];
        try { fr.contentWindow.focus(); fr.contentWindow.print(); } catch (e) { window.open(src, "_blank"); }
    });
    d.$wrapper.addClass("fd-dialog");
    d.show();
}

function fd_install_popup_mode() {
    if (window.__fd_popup_mode_installed) return;
    window.__fd_popup_mode_installed = true;

    // 1. "Create a new X" from any Link field -> always a Quick Entry popup (force=true)
    const proto = frappe.ui.form.ControlLink.prototype;
    const original_new_doc = proto.new_doc;
    proto.new_doc = function () {
        if (!fd_on_console()) return original_new_doc.apply(this, arguments);
        const doctype = this.get_options();
        if (!doctype) return false;
        this.$input._created_new_doc = true;
        frappe.route_options = (this.df && this.df.get_route_options_for_new_doc)
            ? this.df.get_route_options_for_new_doc(this) : {};
        frappe.route_options.name_field = this.get_label_value();
        const me = this;
        frappe.ui.form.make_quick_entry(doctype, (doc) => me.set_value(doc.name), null, null, true);
        return false;
    };

    // 2. The "open link" arrow on Link fields / any a.fd-doc-link -> preview popup instead of navigating
    document.addEventListener("click", (e) => {
        if (!fd_on_console()) return;
        const a = e.target.closest && e.target.closest(".link-btn .btn-open, a.fd-doc-link");
        if (!a) return;
        let doctype = a.dataset.doctype, name = a.dataset.name;
        if (!doctype) {
            const control = $(a).closest(".frappe-control");
            const f = control.data("fieldname");
            const dlg = window.cur_dialog;
            const field = dlg && dlg.fields_dict && dlg.fields_dict[f];
            if (field) { doctype = field.get_options(); name = field.get_value(); }
        }
        if (!doctype || !name) return;
        e.preventDefault();
        e.stopPropagation();
        fd_open_doc_popup(doctype, name);
    }, true);
}

function fd_doc_link(doctype, name, label) {
    if (!name) return "—";
    return `<a class="fd-doc-link" data-doctype="${FD.esc(doctype)}" data-name="${FD.esc(name)}">${FD.esc(label || name)}</a>`;
}
