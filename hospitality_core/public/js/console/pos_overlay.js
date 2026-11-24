/**
 * Sky Hotel Management System - Petpooja-style Advanced Restaurant POS & Kitchen Management Suite
 *
 * Capabilities:
 *  1. Real-Time Check-In / Check-Out: arrival time, departure time, table number, order time, live visit duration.
 *  2. Better Restaurant POS: Floor & table management across areas, live table status (Available, Occupied, Billed, Reserved),
 *     item menu catalog with search & categories, line-item cooking notes, and live order status.
 *  3. Kitchen Management (KDS): Live Kitchen Display System with elapsed timers (Green/Yellow/Red alerts),
 *     cooking notes, and 1-click status transitions (Preparing, Ready, Served).
 *  4. WhatsApp Notifications: Triggered by actual POS & kitchen events:
 *     - Order Ready alert
 *     - Breakfast Ready, Lunch Ready, Dinner Ready meal announcements
 *     - Digital Bill Receipt with 1-click wa.me links
 *  5. Additional Expenses: Transportation, extra food, maintenance, room surcharge, miscellaneous charges
 *     itemized and included in customer billing.
 *  6. Live Dashboard: Active customers, occupied/available tables, active/ready kitchen orders, today's sales,
 *     additional expenses, pending payments.
 *  7. Reports & Analytics: Filterable daily sales, customer additional expenses, payment modes, table turnover & CSV export.
 *  8. Real-Time Updates: Live ticking timers without page refreshes, persistent local state, and room service integration.
 */

// ==========================================
// 1. RESTAURANT STATE & DATA STORE
// ==========================================
class RestaurantStateManager {
    constructor() {
        this.STORAGE_KEY = "sky_hotel_restaurant_pos_state_v3";
        this.MENU_CACHE_KEY = "sky_hotel_restaurant_menu_cache_v3";
        this.state = this.load_state();
        this.menu_items = this.get_default_menu();
        this.load_erpnext_items();
    }

    get_default_tables() {
        return [
            // Main Dining
            { id: "T-01", name: "Table 01", area: "Main Dining", capacity: 2, status: "Available", order: null },
            { id: "T-02", name: "Table 02", area: "Main Dining", capacity: 4, status: "Available", order: null },
            { id: "T-03", name: "Table 03", area: "Main Dining", capacity: 4, status: "Available", order: null },
            { id: "T-04", name: "Table 04", area: "Main Dining", capacity: 6, status: "Available", order: null },
            // AC Family Hall
            { id: "AC-01", name: "AC Table 01", area: "AC Family Hall", capacity: 4, status: "Available", order: null },
            { id: "AC-02", name: "AC Table 02", area: "AC Family Hall", capacity: 6, status: "Available", order: null },
            { id: "AC-03", name: "AC Table 03", area: "AC Family Hall", capacity: 8, status: "Available", order: null },
            // Garden Terrace
            { id: "G-01", name: "Garden 01", area: "Garden Terrace", capacity: 2, status: "Available", order: null },
            { id: "G-02", name: "Garden 02", area: "Garden Terrace", capacity: 4, status: "Available", order: null },
            { id: "G-03", name: "Garden 03", area: "Garden Terrace", capacity: 4, status: "Available", order: null },
            // Rooftop Lounge
            { id: "RT-01", name: "Rooftop 01", area: "Rooftop Lounge", capacity: 4, status: "Available", order: null },
            { id: "RT-02", name: "Rooftop 02", area: "Rooftop Lounge", capacity: 6, status: "Available", order: null },
            { id: "RT-03", name: "Rooftop 03", area: "Rooftop Lounge", capacity: 8, status: "Available", order: null },
            // Poolside
            { id: "P-01", name: "Poolside 01", area: "Poolside", capacity: 2, status: "Available", order: null },
            { id: "P-02", name: "Poolside 02", area: "Poolside", capacity: 4, status: "Available", order: null },
        ];
    }

    get_default_menu() {
        return [
            // Starters
            { code: "APP-01", name: "Paneer Tikka (Tandoori)", category: "Starters", rate: 280, is_veg: 1, desc: "Cottage cheese marinated in royal spices & grilled in tandoor." },
            { code: "APP-02", name: "Crispy Corn Pepper Salt", category: "Starters", rate: 220, is_veg: 1, desc: "Golden sweet corn tossed with bell peppers & crushed black pepper." },
            { code: "APP-03", name: "Chicken Tikka Angara", category: "Starters", rate: 340, is_veg: 0, desc: "Smoky boneless chicken chunks marinated in fiery red spices." },
            { code: "APP-04", name: "Veg Spring Rolls", category: "Starters", rate: 190, is_veg: 1, desc: "Crispy rolls stuffed with julienned vegetables & glass noodles." },
            { code: "APP-05", name: "Tandoori Non-Veg Platter", category: "Starters", rate: 580, is_veg: 0, desc: "Assortment of chicken tikka, seekh kabab, and fish fingers." },
            // Main Course
            { code: "MC-01", name: "Paneer Butter Masala", category: "Main Course", rate: 320, is_veg: 1, desc: "Fresh paneer cooked in velvety rich tomato butter gravy." },
            { code: "MC-02", name: "Dal Makhani Handi", category: "Main Course", rate: 260, is_veg: 1, desc: "Slow-cooked black lentils simmered overnight with butter & cream." },
            { code: "MC-03", name: "Butter Chicken Special", category: "Main Course", rate: 390, is_veg: 0, desc: "Tandoori chicken in mildly spiced creamy tomato butter sauce." },
            { code: "MC-04", name: "Kadai Paneer", category: "Main Course", rate: 310, is_veg: 1, desc: "Paneer cubes tossed with fresh bell peppers, onions, and kadai masala." },
            { code: "MC-05", name: "Mutton Rogan Josh", category: "Main Course", rate: 460, is_veg: 0, desc: "Authentic Kashmiri tender lamb curry infused with ratanjot." },
            // Breads & Rice
            { code: "BR-01", name: "Butter Naan", category: "Breads & Rice", rate: 55, is_veg: 1, desc: "Leavened flatbread brushed with fresh butter." },
            { code: "BR-02", name: "Garlic Naan", category: "Breads & Rice", rate: 65, is_veg: 1, desc: "Tandoor baked naan topped with crushed garlic and cilantro." },
            { code: "BR-03", name: "Tandoori Roti (Butter)", category: "Breads & Rice", rate: 30, is_veg: 1, desc: "Whole wheat roti baked crisp in traditional clay oven." },
            { code: "BR-04", name: "Jeera Rice", category: "Breads & Rice", rate: 180, is_veg: 1, desc: "Aromatic basmati rice tempered with royal cumin seeds." },
            { code: "BR-05", name: "Dum Biryani (Chicken/Veg)", category: "Breads & Rice", rate: 360, is_veg: 0, desc: "Fragrant saffron rice layered with spiced marinated meat/vegetables." },
            // Breakfast
            { code: "BF-01", name: "Masala Dosa with Sambar", category: "Breakfast", rate: 140, is_veg: 1, desc: "Crispy rice crepe filled with potato masala, coconut chutney & sambar." },
            { code: "BF-02", name: "Steamed Idli (2 pcs)", category: "Breakfast", rate: 95, is_veg: 1, desc: "Fluffy steamed rice & lentil cakes served with chutneys." },
            { code: "BF-03", name: "Indori Poha with Sev", category: "Breakfast", rate: 90, is_veg: 1, desc: "Tempered flattened rice with mustard, turmeric, peanuts & crunchy sev." },
            { code: "BF-04", name: "Continental Breakfast Platter", category: "Breakfast", rate: 290, is_veg: 1, desc: "Toasted breads, butter, jam, fresh cut fruits, and juice." },
            // Beverages
            { code: "BV-01", name: "Masala Chai", category: "Beverages", rate: 45, is_veg: 1, desc: "Freshly brewed Indian tea with ginger, cardamom, and herbs." },
            { code: "BV-02", name: "Cold Coffee with Ice Cream", category: "Beverages", rate: 140, is_veg: 1, desc: "Chilled blended coffee topped with vanilla ice cream scoop." },
            { code: "BV-03", name: "Fresh Lime Soda (Sweet/Salt)", category: "Beverages", rate: 85, is_veg: 1, desc: "Refreshing bubbly lime cooler." },
            { code: "BV-04", name: "Sweet Lassi / Mango Lassi", category: "Beverages", rate: 120, is_veg: 1, desc: "Thick creamy churned yogurt shake topped with dry fruits." },
            { code: "BV-05", name: "Mineral Water (1 Litre)", category: "Beverages", rate: 30, is_veg: 1, desc: "Packaged mineral drinking water." },
            // Desserts
            { code: "DS-01", name: "Gulab Jamun (2 pcs)", category: "Desserts", rate: 110, is_veg: 1, desc: "Warm golden milk dumplings soaked in saffron cardamom sugar syrup." },
            { code: "DS-02", name: "Kesari Rasmalai", category: "Desserts", rate: 130, is_veg: 1, desc: "Soft cottage cheese patties in thickened saffron pistachio milk." },
            { code: "DS-03", name: "Sizzling Brownie with Vanilla", category: "Desserts", rate: 220, is_veg: 1, desc: "Warm chocolate brownie on sizzling hot plate with vanilla ice cream." },
        ];
    }

    load_erpnext_items() {
        const me = this;
        if (!window.frappe || !frappe.call) return;
        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "Item",
                fields: ["name", "item_name", "item_group", "standard_rate", "image", "description"],
                filters: { disabled: 0, is_sales_item: 1 },
                limit_page_length: 200,
            },
            callback(r) {
                if (r && r.message && r.message.length) {
                    const db_items = r.message.map((it) => ({
                        code: it.name,
                        name: it.item_name || it.name,
                        category: it.item_group || "General",
                        rate: flt(it.standard_rate) || 150,
                        is_veg: 1,
                        desc: it.description || "",
                    }));
                    // Merge with defaults avoiding duplicate codes
                    const existing_codes = new Set(db_items.map((x) => x.code));
                    const combined = [...db_items];
                    me.get_default_menu().forEach((d) => {
                        if (!existing_codes.has(d.code)) combined.push(d);
                    });
                    me.menu_items = combined;
                }
            },
        });
    }

    load_state() {
        try {
            const raw = localStorage.getItem(this.STORAGE_KEY);
            if (raw) {
                const parsed = JSON.parse(raw);
                if (parsed && Array.isArray(parsed.tables)) return parsed;
            }
        } catch (e) {
            console.error("Failed to load restaurant state", e);
        }
        return {
            tables: this.get_default_tables(),
            sales_history: [],
            additional_expenses_log: [],
            kot_counter: 100,
        };
    }

    save_state() {
        try {
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(this.state));
        } catch (e) {
            console.error("Failed to save restaurant state", e);
        }
    }

    get_table(table_id) {
        return this.state.tables.find((t) => t.id === table_id);
    }

    // ---------------- TABLE CHECK-IN (Customer Arrival) ----------------
    checkin_table(table_id, data) {
        const t = this.get_table(table_id);
        if (!t) return false;

        const arrival_time = data.arrival_time || new Date().toISOString();
        t.status = "Occupied";
        t.order = {
            order_id: "ORD-" + Date.now().toString(36).toUpperCase(),
            table_id: t.id,
            table_name: t.name,
            area: t.area,
            customer_name: data.customer_name || "Walk-in Guest",
            customer_phone: data.customer_phone || "",
            is_in_house: !!data.is_in_house,
            reservation: data.reservation || null,
            room: data.room || null,
            pax: parseInt(data.pax) || t.capacity || 2,
            server_name: data.server_name || "Captain",
            arrival_time: arrival_time,
            order_time: null,
            departure_time: null,
            items: [],
            additional_expenses: [],
            kots: [],
            subtotal: 0,
            extra_charges: 0,
            tax_amount: 0,
            discount_amount: 0,
            grand_total: 0,
            payment_status: "Pending",
            payment_mode: null,
            special_requests: data.special_requests || "",
        };
        this.save_state();
        return t.order;
    }

    // ---------------- ORDER MANAGEMENT & KOT ----------------
    add_item_to_order(table_id, item, qty = 1, notes = "") {
        const t = this.get_table(table_id);
        if (!t || !t.order) return;

        const existing = t.order.items.find((it) => it.code === item.code && it.status === "Pending");
        if (existing) {
            existing.qty += qty;
            existing.amount = flt(existing.qty * existing.rate);
            if (notes) existing.notes = notes;
        } else {
            t.order.items.push({
                item_id: "ITM-" + Date.now().toString(36) + Math.floor(Math.random() * 100),
                code: item.code,
                name: item.name,
                category: item.category || "General",
                rate: flt(item.rate),
                qty: qty,
                amount: flt(qty * item.rate),
                notes: notes || "",
                status: "Pending", // Pending -> Preparing -> Ready -> Served
                kot_no: null,
                ordered_at: null,
            });
        }
        this.recalculate_totals(t.order);
        this.save_state();
    }

    update_item_qty(table_id, item_id, delta) {
        const t = this.get_table(table_id);
        if (!t || !t.order) return;

        const idx = t.order.items.findIndex((it) => it.item_id === item_id);
        if (idx !== -1) {
            const it = t.order.items[idx];
            it.qty += delta;
            if (it.qty <= 0) {
                t.order.items.splice(idx, 1);
            } else {
                it.amount = flt(it.qty * it.rate);
            }
        }
        this.recalculate_totals(t.order);
        this.save_state();
    }

    update_item_notes(table_id, item_id, notes) {
        const t = this.get_table(table_id);
        if (!t || !t.order) return;
        const it = t.order.items.find((x) => x.item_id === item_id);
        if (it) it.notes = notes;
        this.save_state();
    }

    remove_item(table_id, item_id) {
        const t = this.get_table(table_id);
        if (!t || !t.order) return;
        t.order.items = t.order.items.filter((it) => it.item_id !== item_id);
        this.recalculate_totals(t.order);
        this.save_state();
    }

    // Send Pending items to Kitchen as KOT
    send_kot_to_kitchen(table_id) {
        const t = this.get_table(table_id);
        if (!t || !t.order) return null;

        const pending_items = t.order.items.filter((it) => it.status === "Pending");
        if (!pending_items.length) return null;

        this.state.kot_counter = (this.state.kot_counter || 100) + 1;
        const kot_no = this.state.kot_counter;
        const now = new Date().toISOString();

        if (!t.order.order_time) {
            t.order.order_time = now;
        }

        pending_items.forEach((it) => {
            it.status = "Preparing";
            it.kot_no = kot_no;
            it.ordered_at = now;
        });

        const kot_entry = {
            kot_no: kot_no,
            table_id: t.id,
            table_name: t.name,
            area: t.area,
            customer_name: t.order.customer_name,
            customer_phone: t.order.customer_phone,
            room: t.order.room,
            created_at: now,
            status: "Preparing", // Preparing -> Ready -> Served
            items: pending_items.map((it) => ({
                item_id: it.item_id,
                name: it.name,
                qty: it.qty,
                notes: it.notes,
            })),
        };

        t.order.kots.push(kot_entry);
        this.save_state();
        return kot_entry;
    }

    // Update Kitchen status for item or entire KOT
    update_kitchen_status(table_id, kot_no, item_id, new_status) {
        const t = this.get_table(table_id);
        if (!t || !t.order) return;

        if (item_id) {
            const it = t.order.items.find((x) => x.item_id === item_id);
            if (it) it.status = new_status;
        } else if (kot_no) {
            t.order.items.forEach((it) => {
                if (it.kot_no === kot_no) it.status = new_status;
            });
            const kot = t.order.kots.find((k) => k.kot_no === kot_no);
            if (kot) kot.status = new_status;
        }
        this.save_state();
    }

    // ---------------- ADDITIONAL EXPENSES ----------------
    add_additional_expense(table_id, exp_data) {
        const t = this.get_table(table_id);
        if (!t || !t.order) return;

        const entry = {
            expense_id: "EXP-" + Date.now().toString(36) + Math.floor(Math.random() * 100),
            category: exp_data.category || "Miscellaneous",
            description: exp_data.description || "Extra service charge",
            amount: flt(exp_data.amount) || 0,
            is_taxable: exp_data.is_taxable !== false,
            created_at: new Date().toISOString(),
        };

        t.order.additional_expenses.push(entry);
        this.state.additional_expenses_log.unshift(Object.assign({}, entry, {
            table_id: t.id,
            customer_name: t.order.customer_name,
            room: t.order.room,
            order_id: t.order.order_id,
        }));

        this.recalculate_totals(t.order);
        this.save_state();
        return entry;
    }

    remove_additional_expense(table_id, expense_id) {
        const t = this.get_table(table_id);
        if (!t || !t.order) return;
        t.order.additional_expenses = t.order.additional_expenses.filter((x) => x.expense_id !== expense_id);
        this.recalculate_totals(t.order);
        this.save_state();
    }

    recalculate_totals(order) {
        if (!order) return;
        order.subtotal = order.items.reduce((acc, it) => acc + flt(it.amount), 0);
        order.extra_charges = order.additional_expenses.reduce((acc, exp) => acc + flt(exp.amount), 0);
        // 5% standard GST on food & services
        order.tax_amount = Math.round((order.subtotal + order.extra_charges) * 0.05);
        order.grand_total = Math.max(0, order.subtotal + order.extra_charges + order.tax_amount - flt(order.discount_amount));
    }

    // ---------------- SETTLEMENT & CHECK-OUT (Departure) ----------------
    settle_and_checkout(table_id, payment_mode = "Cash") {
        const t = this.get_table(table_id);
        if (!t || !t.order) return null;

        const departure_time = new Date().toISOString();
        const duration_mins = Math.max(1, Math.round((new Date(departure_time) - new Date(t.order.arrival_time)) / 60000));

        t.order.departure_time = departure_time;
        t.order.duration_mins = duration_mins;
        t.order.payment_status = payment_mode === "Room Folio" ? "Charged to Room" : "Paid";
        t.order.payment_mode = payment_mode;

        // Archive into sales history
        const completed_order = Object.assign({}, t.order);
        this.state.sales_history.unshift(completed_order);

        // Reset table
        t.status = "Available";
        const archived = t.order;
        t.order = null;

        this.save_state();
        return archived;
    }

    // ---------------- LIVE DURATION & KPIS ----------------
    get_live_duration_str(arrival_iso, departure_iso = null) {
        if (!arrival_iso) return "—";
        const start = new Date(arrival_iso).getTime();
        const end = departure_iso ? new Date(departure_iso).getTime() : Date.now();
        const diffMs = Math.max(0, end - start);
        const mins = Math.floor(diffMs / 60000);
        const hours = Math.floor(mins / 60);
        const remMins = mins % 60;
        if (hours > 0) return `${hours}h ${remMins}m`;
        return `${mins}m`;
    }

    get_kpi_summary() {
        const occupied = this.state.tables.filter((t) => t.status === "Occupied" || t.status === "Billed");
        const available = this.state.tables.filter((t) => t.status === "Available");
        const active_pax = occupied.reduce((acc, t) => acc + (t.order ? parseInt(t.order.pax || 0) : 0), 0);

        let active_kots = 0;
        let ready_kots = 0;
        let pending_payments = 0;

        occupied.forEach((t) => {
            if (t.order) {
                pending_payments += flt(t.order.grand_total);
                (t.order.kots || []).forEach((k) => {
                    if (k.status === "Preparing") active_kots++;
                    if (k.status === "Ready") ready_kots++;
                });
            }
        });

        const today_str = frappe.datetime.get_today();
        const today_sales = this.state.sales_history
            .filter((o) => (o.departure_time || "").startsWith(today_str))
            .reduce((acc, o) => acc + flt(o.grand_total), 0);

        const today_extra_expenses = this.state.additional_expenses_log
            .filter((e) => (e.created_at || "").startsWith(today_str))
            .reduce((acc, e) => acc + flt(e.amount), 0);

        return {
            active_pax,
            occupied_tables: occupied.length,
            total_tables: this.state.tables.length,
            available_tables: available.length,
            active_kots,
            ready_kots,
            today_sales,
            today_extra_expenses,
            pending_payments,
        };
    }

    get_all_active_kots() {
        const list = [];
        this.state.tables.forEach((t) => {
            if (t.order && Array.isArray(t.order.kots)) {
                t.order.kots.forEach((k) => {
                    list.push(Object.assign({}, k, {
                        order_id: t.order.order_id,
                        arrival_time: t.order.arrival_time,
                    }));
                });
            }
        });
        // Sort newest first
        list.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        return list;
    }
}

// Global Singleton for restaurant state
window.cur_restaurant_manager = new RestaurantStateManager();

// ==========================================
// 2. PETPOOJA RESTAURANT SUITE UI CONTROLLER
// ==========================================
Object.assign(FrontDeskConsole.prototype, {

    open_restaurant_suite(ctx = {}) {
        this.mount_restaurant_pos(null, true, ctx);
    },

    mount_restaurant_pos($container, is_overlay = false, ctx = {}) {
        const me = this;
        const mgr = window.cur_restaurant_manager;

        // If overlay mode requested, mount inside a high-end modal overlay
        let $root = $container;
        if (is_overlay || !$container) {
            $(".fd-pos-overlay").remove();
            const $o = $(`
                <div class="fd-pos-overlay fd-rest-overlay" role="dialog" aria-label="${__("Restaurant POS")}">
                    <div class="fd-rest-mount-point" style="height:100%;display:flex;flex-direction:column;overflow:hidden;"></div>
                </div>`).appendTo("body");
            $("body").addClass("fd-no-scroll");
            $root = $o.find(".fd-rest-mount-point");
            $(document).off("keydown.fdrest").on("keydown.fdrest", (e) => {
                if (e.key === "Escape" && !$(e.target).is("input,textarea")) {
                    $o.remove();
                    $("body").removeClass("fd-no-scroll");
                    $(document).off("keydown.fdrest");
                    if (me.rest_ticker) clearInterval(me.rest_ticker);
                    me.load_data(true);
                }
            });
        }

        this.$rest_root = $root;
        this.rest_current_view = "floor"; // floor | kds | reports
        this.rest_active_area = "All";
        this.rest_selected_table_id = ctx.table_id || null;
        this.rest_menu_category = "All";
        this.rest_menu_search = "";

        this.render_restaurant_layout();
        this.start_restaurant_ticker();
    },

    start_restaurant_ticker() {
        const me = this;
        if (this.rest_ticker) clearInterval(this.rest_ticker);
        this.rest_ticker = setInterval(() => {
            if (!me.$rest_root || !me.$rest_root.is(":visible")) {
                clearInterval(me.rest_ticker);
                return;
            }
            me.update_live_tickers();
        }, 5000);
    },

    update_live_tickers() {
        const mgr = window.cur_restaurant_manager;
        // Update visit durations on table cards
        this.$rest_root.find(".fd-rest-table-card[data-arrival]").each(function () {
            const arr = $(this).attr("data-arrival");
            if (arr) {
                $(this).find(".fd-rest-duration-val").text(mgr.get_live_duration_str(arr));
            }
        });
        // Update KDS elapsed timers
        this.$rest_root.find(".fd-kds-card[data-created]").each(function () {
            const cr = $(this).attr("data-created");
            if (cr) {
                const mins = Math.max(0, Math.floor((Date.now() - new Date(cr).getTime()) / 60000));
                const $badge = $(this).find(".fd-kds-timer");
                $badge.text(`⏱️ ${mins}m ago`);
                $badge.removeClass("alert-green alert-yellow alert-red");
                if (mins < 10) $badge.addClass("alert-green");
                else if (mins < 20) $badge.addClass("alert-yellow");
                else $badge.addClass("alert-red");
            }
        });
        // Refresh KPI ribbon values smoothly
        this.update_kpi_ribbon();
    },

    update_kpi_ribbon() {
        const kpi = window.cur_restaurant_manager.get_kpi_summary();
        const $r = this.$rest_root;
        $r.find("[data-kpi='active_pax']").text(kpi.active_pax);
        $r.find("[data-kpi='occupied_tables']").text(`${kpi.occupied_tables} / ${kpi.total_tables}`);
        $r.find("[data-kpi='available_tables']").text(kpi.available_tables);
        $r.find("[data-kpi='active_kots']").text(kpi.active_kots);
        $r.find("[data-kpi='ready_kots']").text(kpi.ready_kots);
        $r.find("[data-kpi='today_sales']").text(FD.money(kpi.today_sales));
        $r.find("[data-kpi='today_extra']").text(FD.money(kpi.today_extra_expenses));
        $r.find("[data-kpi='pending_payments']").text(FD.money(kpi.pending_payments));
    },

    render_restaurant_layout() {
        const me = this;
        const $r = this.$rest_root.empty();
        const mgr = window.cur_restaurant_manager;
        const kpi = mgr.get_kpi_summary();
        const I = FD.icon;

        const is_modal = $r.closest(".fd-pos-overlay").length > 0;

        $r.html(`
            <div class="fd-rest-suite">
                <!-- TOP HEADER & BRAND BAR -->
                <div class="fd-rest-header">
                    <div class="fd-rest-brand">
                        <span class="fd-rest-brand-icon">${I("utensils", "md")}</span>
                        <div>
                            <div class="fd-rest-brand-title">${__("Sky Restaurant POS")} <span class="badge badge-warning" style="font-size:10px;margin-left:4px;">PRO</span></div>
                            <div class="fd-rest-brand-sub">${__("Petpooja Suite · Tables, Kitchen KDS, WhatsApp & Expenses")}</div>
                        </div>
                    </div>

                    <!-- VIEW SWITCHER -->
                    <div class="fd-rest-nav">
                        <button class="btn btn-sm fd-rest-tab-btn ${this.rest_current_view === "floor" ? "active" : ""}" data-view="floor">
                            ${I("layout-grid")} <span>${__("Tables & Floor")}</span>
                        </button>
                        <button class="btn btn-sm fd-rest-tab-btn ${this.rest_current_view === "kds" ? "active" : ""}" data-view="kds">
                            ${I("flame")} <span>${__("Kitchen KDS")}</span>
                            <span class="badge badge-danger fd-kds-badge" style="margin-left:4px;display:${kpi.active_kots > 0 ? "inline-block" : "none"};">${kpi.active_kots}</span>
                        </button>
                        <button class="btn btn-sm fd-rest-tab-btn ${this.rest_current_view === "reports" ? "active" : ""}" data-view="reports">
                            ${I("bar-chart-2")} <span>${__("Sales & Reports")}</span>
                        </button>
                    </div>

                    <!-- HEADER ACTIONS -->
                    <div class="fd-rest-actions">
                        <button class="btn btn-success btn-sm fd-rest-btn-wa-broadcast" title="${__("Broadcast Breakfast, Lunch, or Dinner ready WhatsApp")}">
                            ${I("message-circle")} <span>${__("Meal WhatsApp")}</span>
                        </button>
                        <button class="btn btn-info btn-sm fd-rest-btn-quick-expense" title="${__("Record extra customer or room charges")}">
                            ${I("plus-circle")} <span>${__("Add Expense")}</span>
                        </button>
                        <button class="btn btn-default btn-sm fd-rest-btn-refresh" title="${__("Sync & Refresh")}">
                            ${I("refresh-cw")}
                        </button>
                        ${is_modal ? `<button class="btn btn-danger btn-sm fd-rest-btn-close">${I("x")} <span>${__("Close")}</span></button>` : ""}
                    </div>
                </div>

                <!-- LIVE KPI RIBBON -->
                <div class="fd-rest-kpis">
                    <div class="fd-rest-kpi-item">
                        <div class="fd-rest-kpi-label">${__("Active Guests")}</div>
                        <div class="fd-rest-kpi-val" data-kpi="active_pax">${kpi.active_pax}</div>
                    </div>
                    <div class="fd-rest-kpi-item">
                        <div class="fd-rest-kpi-label">${__("Tables Occupied")}</div>
                        <div class="fd-rest-kpi-val" data-kpi="occupied_tables">${kpi.occupied_tables} / ${kpi.total_tables}</div>
                    </div>
                    <div class="fd-rest-kpi-item">
                        <div class="fd-rest-kpi-label">${__("Available Tables")}</div>
                        <div class="fd-rest-kpi-val text-success" data-kpi="available_tables">${kpi.available_tables}</div>
                    </div>
                    <div class="fd-rest-kpi-item">
                        <div class="fd-rest-kpi-label">${__("Cooking Orders")}</div>
                        <div class="fd-rest-kpi-val text-warning" data-kpi="active_kots">${kpi.active_kots}</div>
                    </div>
                    <div class="fd-rest-kpi-item">
                        <div class="fd-rest-kpi-label">${__("Ready to Serve")}</div>
                        <div class="fd-rest-kpi-val text-primary" data-kpi="ready_kots">${kpi.ready_kots}</div>
                    </div>
                    <div class="fd-rest-kpi-item">
                        <div class="fd-rest-kpi-label">${__("Today's Sales")}</div>
                        <div class="fd-rest-kpi-val text-success" data-kpi="today_sales">${FD.money(kpi.today_sales)}</div>
                    </div>
                    <div class="fd-rest-kpi-item">
                        <div class="fd-rest-kpi-label">${__("Extra Expenses")}</div>
                        <div class="fd-rest-kpi-val text-info" data-kpi="today_extra">${FD.money(kpi.today_extra_expenses)}</div>
                    </div>
                    <div class="fd-rest-kpi-item">
                        <div class="fd-rest-kpi-label">${__("Pending Payments")}</div>
                        <div class="fd-rest-kpi-val text-danger" data-kpi="pending_payments">${FD.money(kpi.pending_payments)}</div>
                    </div>
                </div>

                <!-- MAIN WORKSPACE VIEW CONTAINER -->
                <div class="fd-rest-main-view"></div>
            </div>
        `);

        // Bind Navigation buttons
        $r.find(".fd-rest-tab-btn").on("click", function () {
            me.rest_current_view = $(this).data("view");
            me.rest_selected_table_id = null;
            $r.find(".fd-rest-tab-btn").removeClass("active");
            $(this).addClass("active");
            me.render_current_view();
        });

        $r.find(".fd-rest-btn-wa-broadcast").on("click", () => me.dialog_restaurant_whatsapp_broadcast());
        $r.find(".fd-rest-btn-quick-expense").on("click", () => me.dialog_add_additional_expense());
        $r.find(".fd-rest-btn-refresh").on("click", () => {
            mgr.save_state();
            me.render_restaurant_layout();
            frappe.show_alert({ message: __("Restaurant data synced"), indicator: "green" });
        });

        if (is_modal) {
            $r.find(".fd-rest-btn-close").on("click", () => {
                $r.closest(".fd-pos-overlay").remove();
                $("body").removeClass("fd-no-scroll");
                if (me.rest_ticker) clearInterval(me.rest_ticker);
                me.load_data(true);
            });
        }

        this.render_current_view();
    },

    render_current_view() {
        const $view = this.$rest_root.find(".fd-rest-main-view").empty();
        if (this.rest_current_view === "floor") {
            if (this.rest_selected_table_id) {
                this.render_table_order_terminal($view, this.rest_selected_table_id);
            } else {
                this.render_floor_plan($view);
            }
        } else if (this.rest_current_view === "kds") {
            this.render_kitchen_kds($view);
        } else if (this.rest_current_view === "reports") {
            this.render_restaurant_reports($view);
        }
    },

    // ==========================================
    // 3. FLOOR PLAN & TABLE MANAGEMENT
    // ==========================================
    render_floor_plan($view) {
        const me = this;
        const mgr = window.cur_restaurant_manager;
        const I = FD.icon;
        const tables = mgr.state.tables;

        const areas = ["All", "Main Dining", "AC Family Hall", "Garden Terrace", "Rooftop Lounge", "Poolside"];

        $view.html(`
            <div class="fd-rest-floor-layout">
                <!-- AREA FILTER TABS -->
                <div class="fd-rest-areas-bar">
                    <div class="fd-rest-areas-list">
                        ${areas.map((a) => `<button class="btn btn-sm fd-rest-area-btn ${this.rest_active_area === a ? "active" : ""}" data-area="${a}">${a}</button>`).join("")}
                    </div>
                    <div class="fd-rest-legend">
                        <span class="fd-legend-item"><span class="fd-dot dot-available"></span> ${__("Available")}</span>
                        <span class="fd-legend-item"><span class="fd-dot dot-occupied"></span> ${__("Occupied / Eating")}</span>
                        <span class="fd-legend-item"><span class="fd-dot dot-billed"></span> ${__("Billed / Settle")}</span>
                    </div>
                </div>

                <!-- TABLES GRID -->
                <div class="fd-rest-table-grid"></div>
            </div>
        `);

        // Bind Area Filter
        $view.find(".fd-rest-area-btn").on("click", function () {
            me.rest_active_area = $(this).data("area");
            $view.find(".fd-rest-area-btn").removeClass("active");
            $(this).addClass("active");
            draw_tables();
        });

        const draw_tables = () => {
            const $grid = $view.find(".fd-rest-table-grid").empty();
            const filtered = tables.filter((t) => me.rest_active_area === "All" || t.area === me.rest_active_area);

            if (!filtered.length) {
                $grid.html(`<div class="text-center p-5 text-muted">${__("No tables found in this section.")}</div>`);
                return;
            }

            filtered.forEach((t) => {
                const order = t.order;
                const is_occupied = t.status === "Occupied" || t.status === "Billed";
                const duration_str = order ? mgr.get_live_duration_str(order.arrival_time) : "";

                // Kitchen items status breakdown
                let cooking_count = 0;
                let ready_count = 0;
                if (order && Array.isArray(order.items)) {
                    order.items.forEach((it) => {
                        if (it.status === "Preparing") cooking_count++;
                        if (it.status === "Ready") ready_count++;
                    });
                }

                const $card = $(`
                    <div class="fd-rest-table-card st-${t.status.toLowerCase()}" data-table="${t.id}" ${order ? `data-arrival="${order.arrival_time}"` : ""}>
                        <div class="fd-table-header">
                            <div>
                                <div class="fd-table-num">${t.name}</div>
                                <div class="fd-table-area">${t.area} · <span class="text-muted">${t.capacity} Pax</span></div>
                            </div>
                            <span class="fd-table-badge badge-${t.status.toLowerCase()}">${t.status}</span>
                        </div>

                        <div class="fd-table-body">
                            ${is_occupied && order ? `
                                <div class="fd-table-guest-line">
                                    <b>${FD.esc(order.customer_name)}</b>
                                    ${order.room ? `<span class="badge badge-info" style="font-size:10px;">🏨 Room ${FD.esc(order.room)}</span>` : ""}
                                </div>
                                <div class="fd-table-timing-row">
                                    <span class="fd-rest-duration-chip" title="${__("Customer visit duration")}">
                                        ⏱️ <span class="fd-rest-duration-val">${duration_str}</span>
                                    </span>
                                    <span class="fd-table-pax">👥 ${order.pax} Guests</span>
                                </div>
                                <div class="fd-table-kitchen-status">
                                    ${ready_count > 0 ? `<span class="badge badge-success fd-badge-pulse">🛎️ ${ready_count} Ready</span>` : ""}
                                    ${cooking_count > 0 ? `<span class="badge badge-warning">🍳 ${cooking_count} Cooking</span>` : ""}
                                    ${!cooking_count && !ready_count && order.items.length ? `<span class="badge badge-default">🍽️ ${order.items.length} Items</span>` : ""}
                                </div>
                                <div class="fd-table-amount-row">
                                    <span class="fd-table-total-lbl">${__("Total Bill")}:</span>
                                    <span class="fd-table-total-val">${FD.money(order.grand_total)}</span>
                                </div>
                            ` : `
                                <div class="fd-table-vacant-state">
                                    <div class="fd-vacant-icon">${I("coffee", "lg")}</div>
                                    <div class="text-muted" style="font-size:12px;">${__("Table Available")}</div>
                                </div>
                            `}
                        </div>

                        <div class="fd-table-actions">
                            ${is_occupied ? `
                                <button class="btn btn-default btn-xs fd-btn-view-order">${I("file-text")} ${__("POS Order")}</button>
                                <button class="btn btn-info btn-xs fd-btn-table-expense" title="${__("Add extra charges")}">+ ${__("Expense")}</button>
                                <button class="btn btn-success btn-xs fd-btn-table-settle">${__("Settle & Exit")}</button>
                            ` : `
                                <button class="btn btn-primary btn-sm btn-block fd-btn-seat-guest">${I("log-in")} ${__("Seat & Check-In")}</button>
                            `}
                        </div>
                    </div>
                `).appendTo($grid);

                // Bind Card Events
                $card.find(".fd-btn-seat-guest").on("click", (e) => {
                    e.stopPropagation();
                    me.dialog_table_checkin(t.id);
                });

                $card.find(".fd-btn-view-order, .fd-table-body").on("click", () => {
                    if (is_occupied) {
                        me.rest_selected_table_id = t.id;
                        me.render_current_view();
                    } else {
                        me.dialog_table_checkin(t.id);
                    }
                });

                $card.find(".fd-btn-table-expense").on("click", (e) => {
                    e.stopPropagation();
                    me.dialog_add_additional_expense(t.id);
                });

                $card.find(".fd-btn-table-settle").on("click", (e) => {
                    e.stopPropagation();
                    me.dialog_settle_order(t.id);
                });
            });
        };

        draw_tables();
    },

    // ---------------- TABLE CHECK-IN MODAL ----------------
    dialog_table_checkin(table_id) {
        const me = this;
        const mgr = window.cur_restaurant_manager;
        const t = mgr.get_table(table_id);
        if (!t) return;

        // In-house guests for 1-click room linking
        const in_house = me.state && me.state.in_house ? me.state.in_house : [];

        const d = FD.dialog({
            title: __("Table Check-In · {0}", [t.name]),
            fields: [
                {
                    fieldtype: "Select",
                    fieldname: "guest_type",
                    label: __("Customer Type"),
                    options: "In-House Hotel Guest\nWalk-In Customer",
                    default: in_house.length ? "In-House Hotel Guest" : "Walk-In Customer",
                },
                {
                    fieldtype: "Select",
                    fieldname: "in_house_res",
                    label: __("Select In-House Room / Guest"),
                    options: ["", ...in_house.map((g) => `${g.room} · ${g.guest_name || g.customer} (${g.name})`)].join("\n"),
                    depends_on: "eval:doc.guest_type=='In-House Hotel Guest'",
                },
                {
                    fieldtype: "Data",
                    fieldname: "customer_name",
                    label: __("Customer / Guest Name"),
                    reqd: 1,
                    default: "Guest",
                },
                {
                    fieldtype: "Data",
                    fieldname: "customer_phone",
                    label: __("WhatsApp / Mobile Number"),
                    description: __("Used for instant Order Ready and Bill Receipt messages"),
                },
                {
                    fieldtype: "Int",
                    fieldname: "pax",
                    label: __("Number of Guests (Pax)"),
                    default: t.capacity || 2,
                    reqd: 1,
                },
                {
                    fieldtype: "Data",
                    fieldname: "server_name",
                    label: __("Captain / Server Name"),
                    default: frappe.session.user_fullname || "Captain",
                },
                {
                    fieldtype: "Datetime",
                    fieldname: "arrival_time",
                    label: __("Arrival Time"),
                    default: frappe.datetime.now_datetime(),
                    reqd: 1,
                },
                {
                    fieldtype: "Small Text",
                    fieldname: "special_requests",
                    label: __("Seating / Table Notes"),
                },
            ],
            primary_action_label: __("Check-In & Start Order 🍽️"),
            primary_action(vals) {
                let room = null;
                let reservation = null;

                if (vals.guest_type === "In-House Hotel Guest" && vals.in_house_res) {
                    const matched = in_house.find((g) => `${g.room} · ${g.guest_name || g.customer} (${g.name})` === vals.in_house_res);
                    if (matched) {
                        room = matched.room;
                        reservation = matched.name;
                    }
                }

                mgr.checkin_table(t.id, {
                    customer_name: vals.customer_name,
                    customer_phone: vals.customer_phone,
                    is_in_house: vals.guest_type === "In-House Hotel Guest",
                    room: room,
                    reservation: reservation,
                    pax: vals.pax,
                    server_name: vals.server_name,
                    arrival_time: vals.arrival_time,
                    special_requests: vals.special_requests,
                });

                d.hide();
                frappe.show_alert({ message: __("Customer checked in to {0}", [t.name]), indicator: "green" });
                // Immediately open Order Terminal
                me.rest_selected_table_id = t.id;
                me.render_current_view();
            },
        });

        // Auto populate customer details when In-House guest is selected
        d.fields_dict.in_house_res.$input.on("change", function () {
            const val = $(this).val();
            const matched = in_house.find((g) => `${g.room} · ${g.guest_name || g.customer} (${g.name})` === val);
            if (matched) {
                d.set_value("customer_name", matched.guest_name || matched.customer);
                if (matched.phone) d.set_value("customer_phone", matched.phone);
            }
        });

        d.show();
    },

    // ==========================================
    // 4. PETPOOJA-STYLE POS ORDER TERMINAL
    // ==========================================
    render_table_order_terminal($view, table_id) {
        const me = this;
        const mgr = window.cur_restaurant_manager;
        const t = mgr.get_table(table_id);
        const I = FD.icon;

        if (!t || !t.order) {
            this.rest_selected_table_id = null;
            this.render_current_view();
            return;
        }

        const order = t.order;
        const categories = ["All", "Starters", "Main Course", "Breads & Rice", "Breakfast", "Beverages", "Desserts"];

        $view.html(`
            <div class="fd-rest-terminal">
                <!-- LEFT 60%: FOOD MENU & CATALOG -->
                <div class="fd-rest-catalog-panel">
                    <div class="fd-terminal-catalog-header">
                        <div class="fd-catalog-search-box">
                            <span class="fd-search-ic">${I("search")}</span>
                            <input type="text" class="form-control input-sm fd-menu-search" placeholder="${__("Search food items, starters, drinks…")}" value="${FD.esc(this.rest_menu_search || "")}">
                        </div>
                        <div class="fd-catalog-cat-bar">
                            ${categories.map((c) => `<button class="btn btn-sm fd-cat-btn ${this.rest_menu_category === c ? "active" : ""}" data-cat="${c}">${c}</button>`).join("")}
                        </div>
                    </div>

                    <!-- MENU ITEMS GRID -->
                    <div class="fd-terminal-menu-grid"></div>
                </div>

                <!-- RIGHT 40%: LIVE ORDER SLIP & BILLING CART -->
                <div class="fd-rest-cart-panel">
                    <!-- TABLE & GUEST HEADER -->
                    <div class="fd-cart-header">
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                <button class="btn btn-default btn-xs fd-btn-back-floor">${I("arrow-left")} ${__("Floor Plan")}</button>
                                <span class="fd-cart-table-title"><b>${t.name}</b> (${t.area})</span>
                            </div>
                            <span class="fd-rest-duration-chip" title="${__("Visit Duration")}">
                                ⏱️ <span class="fd-rest-duration-val">${mgr.get_live_duration_str(order.arrival_time)}</span>
                            </span>
                        </div>
                        <div class="fd-cart-guest-sub">
                            <span>👤 <b>${FD.esc(order.customer_name)}</b> ${order.room ? `<span class="badge badge-info">Room ${order.room}</span>` : ""}</span>
                            <span>👥 ${order.pax} Pax · Waiter: ${FD.esc(order.server_name)}</span>
                        </div>
                    </div>

                    <!-- CART ITEMS LIST -->
                    <div class="fd-cart-items-wrap">
                        <div class="fd-cart-items-list"></div>

                        <!-- ADDITIONAL EXPENSES SECTION -->
                        <div class="fd-cart-extra-expenses">
                            <div class="fd-extra-header">
                                <span><b>${__("Additional Expenses & Services")}</b></span>
                                <button class="btn btn-default btn-xs fd-btn-add-expense-cart">+ ${__("Add Expense")}</button>
                            </div>
                            <div class="fd-extra-items-list"></div>
                        </div>
                    </div>

                    <!-- BILL CALCULATION & SUMMARY -->
                    <div class="fd-cart-summary">
                        <div class="fd-sum-row"><span>${__("Items Subtotal")}</span><span class="fd-sum-val" data-sum="subtotal">${FD.money(order.subtotal)}</span></div>
                        <div class="fd-sum-row"><span>${__("Additional Charges")}</span><span class="fd-sum-val text-info" data-sum="extra">${FD.money(order.extra_charges)}</span></div>
                        <div class="fd-sum-row"><span>${__("GST / Taxes (5%)")}</span><span class="fd-sum-val" data-sum="tax">${FD.money(order.tax_amount)}</span></div>
                        <div class="fd-sum-row fd-sum-grand"><span>${__("Grand Total")}</span><span class="fd-sum-val text-success" data-sum="grand">${FD.money(order.grand_total)}</span></div>
                    </div>

                    <!-- CART ACTION BUTTONS -->
                    <div class="fd-cart-actions">
                        <button class="btn btn-warning btn-sm fd-btn-send-kot">
                            ${I("flame")} <span>${__("Send KOT to Kitchen")}</span>
                        </button>
                        <button class="btn btn-success btn-sm fd-btn-settle-cart">
                            ${I("credit-card")} <span>${__("Settle & Check-Out")}</span>
                        </button>
                        <button class="btn btn-default btn-sm fd-btn-wa-order" title="${__("Send Order Ready WhatsApp")}">
                            ${I("message-circle")}
                        </button>
                        <button class="btn btn-default btn-sm fd-btn-print-bill" title="${__("Print Thermal Bill Receipt")}">
                            ${I("printer")}
                        </button>
                    </div>
                </div>
            </div>
        `);

        // Back to Floor Plan
        $view.find(".fd-btn-back-floor").on("click", () => {
            me.rest_selected_table_id = null;
            me.render_current_view();
        });

        // Search & Category Filters
        $view.find(".fd-menu-search").on("input", function () {
            me.rest_menu_search = $(this).val().toLowerCase();
            render_menu_grid();
        });

        $view.find(".fd-cat-btn").on("click", function () {
            me.rest_menu_category = $(this).data("cat");
            $view.find(".fd-cat-btn").removeClass("active");
            $(this).addClass("active");
            render_menu_grid();
        });

        // Render Menu Items
        const render_menu_grid = () => {
            const $mgrid = $view.find(".fd-terminal-menu-grid").empty();
            const items = mgr.menu_items.filter((it) => {
                const match_cat = me.rest_menu_category === "All" || it.category === me.rest_menu_category;
                const match_search = !me.rest_menu_search ||
                    it.name.toLowerCase().includes(me.rest_menu_search) ||
                    it.code.toLowerCase().includes(me.rest_menu_search);
                return match_cat && match_search;
            });

            if (!items.length) {
                $mgrid.html(`<div class="text-center p-4 text-muted w-100">${__("No items match your search filter.")}</div>`);
                return;
            }

            items.forEach((item) => {
                // Find if item already in order cart
                const in_cart = (order.items || []).find((x) => x.code === item.code);

                const $card = $(`
                    <div class="fd-menu-card" data-code="${item.code}">
                        <div class="fd-menu-card-top">
                            <span class="fd-veg-dot ${item.is_veg ? "veg" : "nonveg"}"></span>
                            <span class="fd-menu-cat-tag">${item.category}</span>
                        </div>
                        <div class="fd-menu-name">${FD.esc(item.name)}</div>
                        <div class="fd-menu-desc text-muted">${FD.esc(item.desc || "")}</div>
                        <div class="fd-menu-foot">
                            <div class="fd-menu-rate">${FD.money(item.rate)}</div>
                            <div class="fd-menu-add-wrap">
                                ${in_cart ? `
                                    <div class="fd-qty-stepper">
                                        <button class="fd-stepper-btn fd-btn-sub">-</button>
                                        <span class="fd-stepper-val">${in_cart.qty}</span>
                                        <button class="fd-stepper-btn fd-btn-add">+</button>
                                    </div>
                                ` : `
                                    <button class="btn btn-default btn-xs fd-btn-add-item">+ ${__("ADD")}</button>
                                `}
                            </div>
                        </div>
                    </div>
                `).appendTo($mgrid);

                $card.find(".fd-btn-add-item").on("click", () => {
                    mgr.add_item_to_order(t.id, item, 1);
                    render_cart();
                    render_menu_grid();
                });

                $card.find(".fd-btn-add").on("click", () => {
                    mgr.add_item_to_order(t.id, item, 1);
                    render_cart();
                    render_menu_grid();
                });

                $card.find(".fd-btn-sub").on("click", () => {
                    if (in_cart) {
                        mgr.update_item_qty(t.id, in_cart.item_id, -1);
                        render_cart();
                        render_menu_grid();
                    }
                });
            });
        };

        // Render Cart Items & Additional Expenses
        const render_cart = () => {
            const $clist = $view.find(".fd-cart-items-list").empty();

            if (!order.items.length) {
                $clist.html(`<div class="text-center p-3 text-muted"><small>${__("No food items ordered yet. Click + ADD from menu.")}</small></div>`);
            } else {
                order.items.forEach((it) => {
                    const status_cls = it.status.toLowerCase();
                    const $item_row = $(`
                        <div class="fd-cart-item-row status-${status_cls}">
                            <div class="fd-cart-item-info">
                                <div class="fd-cart-item-name">
                                    <span>${FD.esc(it.name)}</span>
                                    <span class="badge badge-${status_cls}" style="font-size:9px;margin-left:4px;">${it.status}</span>
                                </div>
                                <div class="fd-cart-item-meta">
                                    <span>${FD.money(it.rate)} each</span>
                                    ${it.notes ? `<span class="fd-cart-item-notes">📝 ${FD.esc(it.notes)}</span>` : ""}
                                </div>
                            </div>
                            <div class="fd-cart-item-stepper">
                                <button class="btn btn-default btn-xs fd-cart-qty-sub">-</button>
                                <span class="fd-cart-qty-val">${it.qty}</span>
                                <button class="btn btn-default btn-xs fd-cart-qty-add">+</button>
                            </div>
                            <div class="fd-cart-item-amt">${FD.money(it.amount)}</div>
                            <div class="fd-cart-item-actions">
                                <button class="btn btn-link btn-xs fd-btn-item-note" title="${__("Cooking Note")}">✏️</button>
                                <button class="btn btn-link btn-xs text-danger fd-btn-item-del" title="${__("Remove Item")}">✕</button>
                            </div>
                        </div>
                    `).appendTo($clist);

                    $item_row.find(".fd-cart-qty-add").on("click", () => {
                        mgr.update_item_qty(t.id, it.item_id, 1);
                        render_cart();
                        render_menu_grid();
                    });

                    $item_row.find(".fd-cart-qty-sub").on("click", () => {
                        mgr.update_item_qty(t.id, it.item_id, -1);
                        render_cart();
                        render_menu_grid();
                    });

                    $item_row.find(".fd-btn-item-del").on("click", () => {
                        mgr.remove_item(t.id, it.item_id);
                        render_cart();
                        render_menu_grid();
                    });

                    $item_row.find(".fd-btn-item-note").on("click", () => {
                        frappe.prompt(
                            { fieldtype: "Data", label: __("Cooking Note for {0}", [it.name]), default: it.notes || "" },
                            (values) => {
                                mgr.update_item_notes(t.id, it.item_id, values.value);
                                render_cart();
                            },
                            __("Add Cooking Note")
                        );
                    });
                });
            }

            // Render Extra Expenses
            const $elist = $view.find(".fd-extra-items-list").empty();
            if (!order.additional_expenses.length) {
                $elist.html(`<div class="text-muted p-1" style="font-size:11px;">${__("No extra expenses added.")}</div>`);
            } else {
                order.additional_expenses.forEach((exp) => {
                    const $erow = $(`
                        <div class="fd-extra-item-row">
                            <div>
                                <span class="badge badge-info" style="font-size:10px;">${FD.esc(exp.category)}</span>
                                <span style="font-size:12px;margin-left:4px;">${FD.esc(exp.description)}</span>
                            </div>
                            <div class="d-flex align-items-center">
                                <b style="font-size:12px;margin-right:6px;">${FD.money(exp.amount)}</b>
                                <button class="btn btn-link btn-xs text-danger fd-btn-del-exp" title="${__("Delete expense")}">✕</button>
                            </div>
                        </div>
                    `).appendTo($elist);

                    $erow.find(".fd-btn-del-exp").on("click", () => {
                        mgr.remove_additional_expense(t.id, exp.expense_id);
                        render_cart();
                    });
                });
            }

            // Update Summary Totals
            $view.find("[data-sum='subtotal']").text(FD.money(order.subtotal));
            $view.find("[data-sum='extra']").text(FD.money(order.extra_charges));
            $view.find("[data-sum='tax']").text(FD.money(order.tax_amount));
            $view.find("[data-sum='grand']").text(FD.money(order.grand_total));
        };

        // Actions
        $view.find(".fd-btn-add-expense-cart").on("click", () => {
            me.dialog_add_additional_expense(t.id, () => render_cart());
        });

        $view.find(".fd-btn-send-kot").on("click", () => {
            const kot = mgr.send_kot_to_kitchen(t.id);
            if (!kot) {
                frappe.msgprint({ title: __("Kitchen KOT"), message: __("All items are already cooking or served."), indicator: "orange" });
                return;
            }
            frappe.show_alert({ message: __("KOT #{0} dispatched to Kitchen Display!", [kot.kot_no]), indicator: "green" });
            render_cart();
        });

        $view.find(".fd-btn-settle-cart").on("click", () => {
            me.dialog_settle_order(t.id);
        });

        $view.find(".fd-btn-wa-order").on("click", () => {
            me.dialog_restaurant_whatsapp(t.id, "order_ready");
        });

        $view.find(".fd-btn-print-bill").on("click", () => {
            me.print_thermal_receipt(t.id);
        });

        render_menu_grid();
        render_cart();
    },

    // ==========================================
    // 5. KITCHEN MANAGEMENT (KDS)
    // ==========================================
    render_kitchen_kds($view) {
        const me = this;
        const mgr = window.cur_restaurant_manager;
        const I = FD.icon;
        const kots = mgr.get_all_active_kots();

        $view.html(`
            <div class="fd-rest-kds-layout">
                <div class="fd-kds-toolbar">
                    <div class="fd-kds-title">
                        ${I("flame")} <span>${__("Kitchen Display System (KDS)")}</span>
                        <span class="badge badge-danger" style="margin-left:6px;">${kots.length} ${__("Active Tickets")}</span>
                    </div>
                    <div class="fd-kds-filters">
                        <span class="text-muted" style="font-size:12px;">${__("Auto-refreshes in real-time · Green <10m | Yellow 10-20m | Red >20m")}</span>
                    </div>
                </div>

                <div class="fd-kds-cards-grid"></div>
            </div>
        `);

        const $grid = $view.find(".fd-kds-cards-grid").empty();

        if (!kots.length) {
            $grid.html(`
                <div class="fd-kds-empty">
                    <div class="fd-kds-empty-icon">${I("check-circle", "xl")}</div>
                    <h3>${__("Kitchen is all caught up!")}</h3>
                    <p class="text-muted">${__("New orders sent from the POS will appear here with live elapsed timers.")}</p>
                </div>
            `);
            return;
        }

        kots.forEach((kot) => {
            const mins = Math.max(0, Math.floor((Date.now() - new Date(kot.created_at).getTime()) / 60000));
            let timer_cls = "alert-green";
            if (mins >= 10 && mins < 20) timer_cls = "alert-yellow";
            if (mins >= 20) timer_cls = "alert-red";

            const $card = $(`
                <div class="fd-kds-card" data-table="${kot.table_id}" data-kot="${kot.kot_no}" data-created="${kot.created_at}">
                    <div class="fd-kds-card-head">
                        <div>
                            <div class="fd-kds-kot-num">KOT #${kot.kot_no}</div>
                            <div class="fd-kds-table-name"><b>${kot.table_name}</b> (${kot.area}) ${kot.room ? `· Room ${kot.room}` : ""}</div>
                        </div>
                        <div class="fd-kds-timer ${timer_cls}">⏱️ ${mins}m ago</div>
                    </div>

                    <div class="fd-kds-items">
                        ${kot.items.map((it) => `
                            <div class="fd-kds-item-row">
                                <span class="fd-kds-item-qty">x${it.qty}</span>
                                <span class="fd-kds-item-name">${FD.esc(it.name)}</span>
                                ${it.notes ? `<div class="fd-kds-item-notes">⚠️ ${FD.esc(it.notes)}</div>` : ""}
                            </div>
                        `).join("")}
                    </div>

                    <div class="fd-kds-actions">
                        ${kot.status === "Preparing" ? `
                            <button class="btn btn-success btn-sm btn-block fd-btn-kds-ready">
                                ✅ ${__("Mark Food Ready (Alert WhatsApp)")}
                            </button>
                        ` : `
                            <button class="btn btn-primary btn-sm btn-block fd-btn-kds-serve">
                                🍽️ ${__("Mark Served to Table")}
                            </button>
                        `}
                    </div>
                </div>
            `).appendTo($grid);

            $card.find(".fd-btn-kds-ready").on("click", () => {
                mgr.update_kitchen_status(kot.table_id, kot.kot_no, null, "Ready");
                frappe.show_alert({ message: __("KOT #{0} marked READY! 🛎️", [kot.kot_no]), indicator: "green" });
                me.render_kitchen_kds($view);
                // Prompt to notify customer via WhatsApp
                me.dialog_restaurant_whatsapp(kot.table_id, "order_ready");
            });

            $card.find(".fd-btn-kds-serve").on("click", () => {
                mgr.update_kitchen_status(kot.table_id, kot.kot_no, null, "Served");
                frappe.show_alert({ message: __("KOT #{0} served to table.", [kot.kot_no]), indicator: "blue" });
                me.render_kitchen_kds($view);
            });
        });
    },

    // ==========================================
    // 6. ADDITIONAL EXPENSES DIALOG
    // ==========================================
    dialog_add_additional_expense(default_table_id = null, callback = null) {
        const me = this;
        const mgr = window.cur_restaurant_manager;
        const occupied = mgr.state.tables.filter((t) => t.status === "Occupied" || t.status === "Billed");

        if (!occupied.length) {
            frappe.msgprint({
                title: __("No Active Tables"),
                message: __("There are no occupied tables right now. Please check-in a customer or guest first to attach additional expenses."),
                indicator: "orange",
            });
            return;
        }

        const table_options = occupied.map((t) => `${t.id} · ${t.name} (${t.order.customer_name}${t.order.room ? ` - Room ${t.order.room}` : ""})`);

        const d = FD.dialog({
            title: __("Add Additional Expense / Miscellaneous Charge"),
            fields: [
                {
                    fieldtype: "Select",
                    fieldname: "table_pick",
                    label: __("Select Table / Order"),
                    options: table_options.join("\n"),
                    default: default_table_id ? table_options.find((x) => x.startsWith(default_table_id)) : table_options[0],
                    reqd: 1,
                },
                {
                    fieldtype: "Select",
                    fieldname: "category",
                    label: __("Expense Category"),
                    options: [
                        "Transportation / Airport Cab",
                        "Extra Food / Special Chef Request",
                        "Room Surcharge / Late Checkout",
                        "Maintenance / Damage Fee",
                        "Spa & Wellness Services",
                        "Beverage / Corkage Charge",
                        "Miscellaneous / Other Charges",
                    ].join("\n"),
                    default: "Extra Food / Special Chef Request",
                    reqd: 1,
                },
                {
                    fieldtype: "Data",
                    fieldname: "description",
                    label: __("Description / Reason"),
                    placeholder: __("e.g. Airport cab sedan, special imported cheese, swimming pool towel fee…"),
                    reqd: 1,
                },
                {
                    fieldtype: "Currency",
                    fieldname: "amount",
                    label: __("Charge Amount"),
                    reqd: 1,
                },
                {
                    fieldtype: "Check",
                    fieldname: "is_taxable",
                    label: __("Apply standard GST / Tax on this charge"),
                    default: 1,
                },
            ],
            primary_action_label: __("Add to Customer Bill ➕"),
            primary_action(vals) {
                const table_id = vals.table_pick.split(" · ")[0];
                mgr.add_additional_expense(table_id, {
                    category: vals.category,
                    description: vals.description,
                    amount: flt(vals.amount),
                    is_taxable: !!vals.is_taxable,
                });
                d.hide();
                frappe.show_alert({ message: __("Expense of {0} added to {1}", [FD.money(vals.amount), table_id]), indicator: "green" });
                if (callback) callback();
                else me.render_current_view();
            },
        });

        d.show();
    },

    // ==========================================
    // 7. SETTLEMENT & CHECK-OUT MODAL
    // ==========================================
    dialog_settle_order(table_id) {
        const me = this;
        const mgr = window.cur_restaurant_manager;
        const t = mgr.get_table(table_id);
        if (!t || !t.order) return;

        const order = t.order;
        const duration_str = mgr.get_live_duration_str(order.arrival_time);

        const d = FD.dialog({
            title: __("Bill Settlement & Check-Out · {0}", [t.name]),
            fields: [
                {
                    fieldtype: "HTML",
                    fieldname: "bill_summary",
                },
                {
                    fieldtype: "Select",
                    fieldname: "payment_mode",
                    label: __("Payment Mode"),
                    options: [
                        "Cash",
                        "Card / POS Machine",
                        "UPI / QR Code",
                        order.is_in_house ? "Room Folio (Charge to Stay Invoice)" : "",
                    ].filter(Boolean).join("\n"),
                    default: "Cash",
                    reqd: 1,
                },
                {
                    fieldtype: "Check",
                    fieldname: "send_whatsapp",
                    label: __("Send Digital Bill Receipt on WhatsApp 📱"),
                    default: order.customer_phone ? 1 : 0,
                },
            ],
            primary_action_label: __("Settle Payment & Check-Out Table ✅"),
            primary_action(vals) {
                const archived = mgr.settle_and_checkout(t.id, vals.payment_mode);
                d.hide();
                frappe.show_alert({ message: __("Table {0} settled and checked out!", [t.name]), indicator: "green" });
                me.rest_selected_table_id = null;
                me.render_current_view();

                if (vals.send_whatsapp && order.customer_phone) {
                    me.dialog_restaurant_whatsapp(null, "bill_receipt", archived);
                }
            },
        });

        d.fields_dict.bill_summary.$wrapper.html(`
            <div class="fd-settle-card">
                <div class="fd-settle-header">
                    <div><b>${FD.esc(order.customer_name)}</b> ${order.room ? `· Room ${order.room}` : ""}</div>
                    <div class="text-muted"><small>⏱️ Duration: <b>${duration_str}</b> (Arrived: ${frappe.datetime.str_to_user(order.arrival_time)})</small></div>
                </div>

                <div class="fd-settle-breakdown">
                    <div class="d-flex justify-content-between p-1"><span>${__("Food & Beverages Total")}</span><b>${FD.money(order.subtotal)}</b></div>
                    <div class="d-flex justify-content-between p-1"><span>${__("Additional Miscellaneous Charges")}</span><b class="text-info">${FD.money(order.extra_charges)}</b></div>
                    <div class="d-flex justify-content-between p-1"><span>${__("GST Taxes (5%)")}</span><b>${FD.money(order.tax_amount)}</b></div>
                    <div class="d-flex justify-content-between p-1 fd-settle-grand"><span>${__("Grand Total Payable")}</span><b class="text-success">${FD.money(order.grand_total)}</b></div>
                </div>
            </div>
        `);

        d.show();
    },

    // ==========================================
    // 8. WHATSAPP NOTIFICATIONS ENGINE
    // ==========================================
    dialog_restaurant_whatsapp(table_id = null, msg_type = "order_ready", archived_order = null) {
        const me = this;
        const mgr = window.cur_restaurant_manager;
        const hotel_name = (this.state && this.state.settings && this.state.settings.hotel_name) || "Sky Hotel & Restaurant";

        let order = archived_order;
        if (!order && table_id) {
            const t = mgr.get_table(table_id);
            order = t ? t.order : null;
        }

        let guest_name = order ? order.customer_name : "Valued Guest";
        let phone = order ? order.customer_phone : "";
        let table_str = order ? order.table_name : "Your Table";

        let default_text = "";

        if (msg_type === "order_ready") {
            const items_str = order && order.items ? order.items.map((x) => `• ${x.qty}x ${x.name}`).join("\n") : "Your delicious dishes";
            default_text =
                `Hello *${guest_name}*! 🛎️✨\n\n` +
                `Your food order for *${table_str}* is freshly prepared and *READY* at *${hotel_name}* Restaurant!\n\n` +
                `🍽️ *Ready Items:*\n${items_str}\n\n` +
                `Please enjoy your meal! Let us know if you need anything else. 😊`;
        } else if (msg_type === "breakfast_ready") {
            default_text =
                `Good morning *${guest_name}*! 🥐☕\n\n` +
                `Delicious Breakfast Buffet is now freshly served and open at *${hotel_name}* Dining Hall!\n\n` +
                `Join us for fluffy idlis, dosas, pancakes, fresh juices, and hot masala chai. We look forward to serving you! 🥞🍳`;
        } else if (msg_type === "lunch_ready") {
            default_text =
                `Good afternoon *${guest_name}*! 🍛🥗\n\n` +
                `Chef's Special Lunch Buffet is now ready and served at *${hotel_name}* Restaurant!\n\n` +
                `Come savor our delicious curries, tandoori rotis, fragrant biryanis, and delightful desserts. 🍲✨`;
        } else if (msg_type === "dinner_ready") {
            default_text =
                `Good evening *${guest_name}*! 🍲🍷\n\n` +
                `Fine Dining Dinner is now open at *${hotel_name}* Restaurant!\n\n` +
                `Relax and enjoy a wonderful culinary evening with our signature dishes and special mocktails. 🍽️✨`;
        } else if (msg_type === "bill_receipt") {
            const grand = order ? FD.money(order.grand_total) : "0.00";
            const mode = order ? order.payment_mode : "Paid";
            const dur = order ? `${order.duration_mins || 30} mins` : "";

            default_text =
                `Hello *${guest_name}*! 🧾✨\n\n` +
                `Thank you for dining with us at *${hotel_name}*!\n\n` +
                `*Bill Summary - ${table_str}*\n` +
                `--------------------------\n` +
                `Food & Drinks: ${order ? FD.money(order.subtotal) : ""}\n` +
                `Additional Charges: ${order ? FD.money(order.extra_charges) : ""}\n` +
                `Taxes: ${order ? FD.money(order.tax_amount) : ""}\n` +
                `*Grand Total: ${grand}*\n` +
                `Payment Mode: *${mode} (PAID)*\n` +
                `Visit Duration: ${dur}\n` +
                `--------------------------\n\n` +
                `We hope you had a fantastic experience! Have a wonderful day ahead! 😊`;
        }

        const d = FD.dialog({
            title: __("Send WhatsApp Notification 💬"),
            fields: [
                {
                    fieldtype: "Data",
                    fieldname: "phone",
                    label: __("Recipient Mobile Number (with country code)"),
                    default: phone,
                    reqd: 1,
                },
                {
                    fieldtype: "Small Text",
                    fieldname: "message",
                    label: __("WhatsApp Message"),
                    default: default_text,
                    reqd: 1,
                },
            ],
            primary_action_label: __("Open in WhatsApp 📱"),
            primary_action(vals) {
                let clean_phone = String(vals.phone).replace(/[^0-9]/g, "");
                if (clean_phone.length === 10) clean_phone = "91" + clean_phone;

                const url = `https://wa.me/${clean_phone}?text=${encodeURIComponent(vals.message)}`;
                window.open(url, "_blank");
                d.hide();
                frappe.show_alert({ message: __("Opening WhatsApp chat…"), indicator: "green" });
            },
        });

        d.show();
    },

    dialog_restaurant_whatsapp_broadcast() {
        const me = this;
        const d = FD.dialog({
            title: __("Restaurant Meal WhatsApp Broadcast"),
            fields: [
                {
                    fieldtype: "Select",
                    fieldname: "meal_type",
                    label: __("Select Meal Notification"),
                    options: [
                        "breakfast_ready|🥐 Breakfast Ready Announcement",
                        "lunch_ready|🍛 Lunch Ready Announcement",
                        "dinner_ready|🍲 Dinner Ready Announcement",
                    ].join("\n"),
                    default: "breakfast_ready",
                    reqd: 1,
                },
            ],
            primary_action_label: __("Compose & Send 💬"),
            primary_action(vals) {
                d.hide();
                me.dialog_restaurant_whatsapp(null, vals.meal_type);
            },
        });
        d.show();
    },

    // ==========================================
    // 9. REPORTS & ANALYTICS VIEW
    // ==========================================
    render_restaurant_reports($view) {
        const me = this;
        const mgr = window.cur_restaurant_manager;
        const I = FD.icon;
        const sales = mgr.state.sales_history || [];
        const extra_log = mgr.state.additional_expenses_log || [];

        const total_sales = sales.reduce((acc, o) => acc + flt(o.grand_total), 0);
        const total_extra = extra_log.reduce((acc, e) => acc + flt(e.amount), 0);
        const total_orders = sales.length;
        const avg_duration = total_orders ? Math.round(sales.reduce((acc, o) => acc + (o.duration_mins || 30), 0) / total_orders) : 0;

        $view.html(`
            <div class="fd-rest-reports-layout">
                <!-- REPORT TOP CARDS -->
                <div class="fd-reports-summary-row">
                    <div class="fd-rep-kpi-card">
                        <div class="fd-rep-lbl">${__("Total Revenue")}</div>
                        <div class="fd-rep-val text-success">${FD.money(total_sales)}</div>
                    </div>
                    <div class="fd-rep-kpi-card">
                        <div class="fd-rep-lbl">${__("Additional Expenses Collected")}</div>
                        <div class="fd-rep-val text-info">${FD.money(total_extra)}</div>
                    </div>
                    <div class="fd-rep-kpi-card">
                        <div class="fd-rep-lbl">${__("Total Completed Orders")}</div>
                        <div class="fd-rep-val">${total_orders}</div>
                    </div>
                    <div class="fd-rep-kpi-card">
                        <div class="fd-rep-lbl">${__("Average Table Duration")}</div>
                        <div class="fd-rep-val text-primary">${avg_duration} mins</div>
                    </div>
                </div>

                <!-- TABS FOR SALES VS EXPENSES -->
                <div class="fd-rep-tabs-wrap">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <div class="btn-group">
                            <button class="btn btn-default btn-sm active fd-rep-switch-sales">${I("shopping-cart")} ${__("Daily Sales Log")}</button>
                            <button class="btn btn-default btn-sm fd-rep-switch-extra">${I("plus-circle")} ${__("Customer Extra Charges")}</button>
                        </div>
                        <button class="btn btn-default btn-sm fd-btn-export-csv">${I("download")} ${__("Export CSV")}</button>
                    </div>

                    <div class="fd-rep-table-holder"></div>
                </div>
            </div>
        `);

        const render_sales_table = () => {
            const $tbl = $view.find(".fd-rep-table-holder").empty();
            if (!sales.length) {
                $tbl.html(`<div class="text-center p-5 text-muted">${__("No completed orders yet. Settled orders will appear here.")}</div>`);
                return;
            }

            $tbl.html(`
                <table class="table table-bordered table-hover fd-rep-grid">
                    <thead>
                        <tr>
                            <th>${__("Order ID")}</th>
                            <th>${__("Table / Area")}</th>
                            <th>${__("Customer Name")}</th>
                            <th>${__("Arrival")}</th>
                            <th>${__("Departure")}</th>
                            <th>${__("Duration")}</th>
                            <th>${__("Food Subtotal")}</th>
                            <th>${__("Extra Charges")}</th>
                            <th>${__("Grand Total")}</th>
                            <th>${__("Payment Mode")}</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${sales.map((o) => `
                            <tr>
                                <td><b>${o.order_id}</b></td>
                                <td>${o.table_name} (${o.area}) ${o.room ? `<span class="badge badge-info">Rm ${o.room}</span>` : ""}</td>
                                <td>${FD.esc(o.customer_name)}</td>
                                <td>${frappe.datetime.str_to_user(o.arrival_time)}</td>
                                <td>${frappe.datetime.str_to_user(o.departure_time)}</td>
                                <td><b>${o.duration_mins || 30}m</b></td>
                                <td>${FD.money(o.subtotal)}</td>
                                <td class="text-info">${FD.money(o.extra_charges)}</td>
                                <td class="text-success font-weight-bold">${FD.money(o.grand_total)}</td>
                                <td><span class="badge badge-default">${o.payment_mode || "Paid"}</span></td>
                            </tr>
                        `).join("")}
                    </tbody>
                </table>
            `);
        };

        const render_extra_table = () => {
            const $tbl = $view.find(".fd-rep-table-holder").empty();
            if (!extra_log.length) {
                $tbl.html(`<div class="text-center p-5 text-muted">${__("No additional charges recorded yet.")}</div>`);
                return;
            }

            $tbl.html(`
                <table class="table table-bordered table-hover fd-rep-grid">
                    <thead>
                        <tr>
                            <th>${__("Date & Time")}</th>
                            <th>${__("Customer / Room")}</th>
                            <th>${__("Category")}</th>
                            <th>${__("Description / Reason")}</th>
                            <th>${__("Amount")}</th>
                            <th>${__("Taxable")}</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${extra_log.map((e) => `
                            <tr>
                                <td>${frappe.datetime.str_to_user(e.created_at)}</td>
                                <td>${FD.esc(e.customer_name || "Guest")} ${e.room ? `(Room ${e.room})` : `(${e.table_id})`}</td>
                                <td><span class="badge badge-info">${FD.esc(e.category)}</span></td>
                                <td>${FD.esc(e.description)}</td>
                                <td class="text-info font-weight-bold">${FD.money(e.amount)}</td>
                                <td>${e.is_taxable ? "Yes (5% GST)" : "No"}</td>
                            </tr>
                        `).join("")}
                    </tbody>
                </table>
            `);
        };

        $view.find(".fd-rep-switch-sales").on("click", function () {
            $view.find(".btn-group button").removeClass("active");
            $(this).addClass("active");
            render_sales_table();
        });

        $view.find(".fd-rep-switch-extra").on("click", function () {
            $view.find(".btn-group button").removeClass("active");
            $(this).addClass("active");
            render_extra_table();
        });

        // CSV Export
        $view.find(".fd-btn-export-csv").on("click", () => {
            const headers = ["Order ID", "Table", "Customer", "Arrival", "Departure", "Duration Mins", "Subtotal", "Extra Charges", "Grand Total", "Payment Mode"];
            const rows = sales.map((o) => [
                o.order_id,
                o.table_name,
                `"${(o.customer_name || "").replace(/"/g, '""')}"`,
                o.arrival_time,
                o.departure_time,
                o.duration_mins || 30,
                o.subtotal,
                o.extra_charges,
                o.grand_total,
                o.payment_mode || "Paid",
            ]);
            const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
            const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
            const link = document.createElement("a");
            link.href = URL.createObjectURL(blob);
            link.download = `Restaurant_Sales_Report_${frappe.datetime.get_today()}.csv`;
            link.click();
        });

        render_sales_table();
    },

    // ==========================================
    // 10. THERMAL RECEIPT PRINTING
    // ==========================================
    print_thermal_receipt(table_id) {
        const mgr = window.cur_restaurant_manager;
        const t = mgr.get_table(table_id);
        if (!t || !t.order) return;

        const order = t.order;
        const hotel_name = (this.state && this.state.settings && this.state.settings.hotel_name) || "Sky Hotel & Restaurant";
        const contact = (this.state && this.state.settings && this.state.settings.contact_number) || "";

        const w = window.open("", "_blank", "width=380,height=600");
        if (!w) return;

        const html = `
            <!DOCTYPE html>
            <html>
            <head>
                <title>Receipt - ${order.order_id}</title>
                <style>
                    body { font-family: monospace; font-size: 12px; margin: 0; padding: 10px; width: 280px; }
                    .center { text-align: center; }
                    .hr { border-bottom: 1px dashed #000; margin: 8px 0; }
                    .row { display: flex; justify-content: space-between; margin-bottom: 4px; }
                    .bold { font-weight: bold; }
                </style>
            </head>
            <body>
                <div class="center bold" style="font-size:14px;">${hotel_name}</div>
                <div class="center">RESTAURANT RECEIPT</div>
                ${contact ? `<div class="center">Tel: ${contact}</div>` : ""}
                <div class="hr"></div>
                <div class="row"><span>Table: <b>${t.name}</b></span><span>Pax: ${order.pax}</span></div>
                <div class="row"><span>Guest: ${order.customer_name}</span>${order.room ? `<span>Rm: ${order.room}</span>` : ""}</div>
                <div class="row"><span>Time: ${frappe.datetime.now_datetime()}</span></div>
                <div class="row"><span>Duration: <b>${mgr.get_live_duration_str(order.arrival_time)}</b></span></div>
                <div class="hr"></div>
                ${order.items.map((it) => `<div class="row"><span>${it.qty}x ${it.name}</span><span>${FD.money(it.amount)}</span></div>`).join("")}
                ${order.additional_expenses.length ? `
                    <div class="hr"></div>
                    <div class="bold">Additional Expenses:</div>
                    ${order.additional_expenses.map((e) => `<div class="row"><span>+ ${e.category}</span><span>${FD.money(e.amount)}</span></div>`).join("")}
                ` : ""}
                <div class="hr"></div>
                <div class="row"><span>Subtotal:</span><span>${FD.money(order.subtotal)}</span></div>
                ${order.extra_charges ? `<div class="row"><span>Extra Charges:</span><span>${FD.money(order.extra_charges)}</span></div>` : ""}
                <div class="row"><span>GST (5%):</span><span>${FD.money(order.tax_amount)}</span></div>
                <div class="row bold" style="font-size:14px;"><span>GRAND TOTAL:</span><span>${FD.money(order.grand_total)}</span></div>
                <div class="hr"></div>
                <div class="center">Thank you for dining with us!</div>
                <script>window.print();</script>
            </body>
            </html>
        `;
        w.document.write(html);
        w.document.close();
    },

    // ==========================================
    // 11. BACKWARD COMPATIBLE POS LAUNCHERS
    // ==========================================
    dialog_pick_room_service_guest() {
        const me = this;
        const guests = this.state.in_house || [];
        if (!guests.length) {
            frappe.msgprint({ title: __("Room Service"), message: __("No guests are checked in. Room service can only be charged to in-house guests."), indicator: "orange" });
            return;
        }
        const d = FD.dialog({
            title: __("Room Service · Select Guest"),
            fields: [{ fieldtype: "HTML", fieldname: "list" }],
        });
        d.fields_dict.list.$wrapper.html(`<div class="fd-guest-pick">${guests.map((g) => `
            <button class="fd-guest-pick-item" data-res="${FD.esc(g.name)}" data-cust="${FD.esc(g.customer)}">
                <span class="fd-rc-num">${FD.esc(g.room)}</span>
                <span><b>${FD.esc(g.guest_name || g.customer)}</b><small class="text-muted d-block">${FD.esc(g.name)}</small></span>
            </button>`).join("")}</div>
            <button class="btn btn-default btn-sm mt-3 fd-guest-none">${__("Open without guest")}</button>`);
        d.fields_dict.list.$wrapper.on("click", ".fd-guest-pick-item", function () {
            d.hide();
            me.open_room_service_for($(this).data("res"), $(this).data("cust"));
        });
        d.fields_dict.list.$wrapper.on("click", ".fd-guest-none", () => { d.hide(); me.open_pos_overlay("room"); });
        d.show();
    },

    open_room_service_for(reservation, customer) {
        if (!customer) {
            const g = (this.state.in_house || []).find((x) => x.name === reservation);
            customer = g && g.customer;
        }
        this.open_pos_overlay("room", { reservation, customer });
    },

    open_pos_overlay(type = "room", ctx = {}) {
        if (type === "restaurant") {
            // Launch the Petpooja Restaurant Suite overlay directly!
            this.open_restaurant_suite(ctx);
            return;
        }

        const me = this;
        const s = this.state.settings || {};
        const profile = s.room_pos_profile;
        const label = __("Room Service POS");

        if (!profile) {
            frappe.msgprint({
                title: __("Setup required"), indicator: "orange",
                message: __("No {0} profile is configured in Hotel Settings.", [label]) +
                    `<br><br><button class="btn btn-sm btn-primary fd-open-settings-msg">${__("Open Hotel Settings")}</button>`,
            });
            $(".fd-open-settings-msg").on("click", () => { frappe.hide_msgprint(); me.dialog_hotel_settings(); });
            return;
        }

        FD.call("hospitality_core.api.console.ensure_pos_opening", { pos_profile: profile }, { freeze: true, freeze_message: __("Opening POS…") })
            .then(() => {
                try {
                    localStorage.setItem("hotel_pos_launch", JSON.stringify({
                        profile, customer: ctx.customer || null, reservation: ctx.reservation || null, ts: Date.now(),
                    }));
                } catch (e) { /* storage unavailable */ }

                const url = "/desk/point-of-sale";
                $(".fd-pos-overlay").remove();
                const $o = $(`
                    <div class="fd-pos-overlay" role="dialog" aria-label="${FD.esc(label)}">
                        <div class="fd-pos-header">
                            <div class="fd-pos-title">${FD.icon("bell")}
                                <b>${FD.esc(label)}</b><span class="fd-pos-badge">${FD.esc(profile)}</span>
                                ${ctx.reservation ? `<span class="fd-pos-badge">${__("Guest")}: ${FD.esc(ctx.reservation)}</span>` : ""}
                            </div>
                            <div>
                                <button class="btn btn-default btn-sm fd-pos-newtab">${__("Open in new tab")}</button>
                                <button class="btn btn-danger btn-sm fd-close-pos">${FD.icon("x")} ${__("Close")}</button>
                            </div>
                        </div>
                        <div class="fd-pos-loading">${__("Loading Point of Sale…")}</div>
                        <iframe class="fd-pos-iframe" src="${url}"></iframe>
                    </div>`).appendTo("body");
                $("body").addClass("fd-no-scroll");
                const close = () => { $o.remove(); $("body").removeClass("fd-no-scroll"); $(document).off("keydown.fdpos"); me.load_data(true); };
                $o.find(".fd-close-pos").on("click", close);
                $o.find(".fd-pos-newtab").on("click", () => { window.open(url, "_blank"); close(); });
                $(document).on("keydown.fdpos", (e) => { if (e.key === "Escape" && !$(e.target).is("input,textarea")) close(); });
                const iframe = $o.find("iframe")[0];
                const fallback = setTimeout(() => {
                    let ok = false;
                    try { ok = !!(iframe.contentWindow && iframe.contentWindow.frappe); } catch (e) { ok = false; }
                    if (!ok) $o.find(".fd-pos-loading").html(`${__("POS could not be embedded.")} <button class="btn btn-sm btn-primary fd-pos-fallback">${__("Open in new tab")}</button>`)
                        .find(".fd-pos-fallback").on("click", () => { window.open(url, "_blank"); close(); });
                }, 15000);
                iframe.addEventListener("load", () => {
                    try {
                        if (iframe.contentWindow && iframe.contentWindow.frappe) {
                            clearTimeout(fallback);
                            $o.find(".fd-pos-loading").hide();
                        }
                    } catch (e) { /* cross-origin */ }
                });
            });
    },
});
