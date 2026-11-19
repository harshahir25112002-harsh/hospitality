# OTA Integration Guide (Channex Channel Manager)

## Sky Hotel Management System (Hospitality Core)

This guide explains how to connect your ERPNext hotel management system to Online Travel Agencies (OTAs) like **MakeMyTrip, Booking.com, Agoda, Expedia, Goibibo**, and more using **Channex**.

---

## 1. Architecture Overview

```
[ OTAs: MakeMyTrip, Agoda, Booking.com ]
                │
                ▼
         [ Channex.io ]
          │          ▲
(Real-time Webhook)   │ (Availability & Rate Push)
          │          │
          ▼          │
 [ ERPNext Hospitality Core ]
   ├── Webhook Endpoint: /api/method/hospitality_core.api.ota.webhook
   ├── Backup Pull Feed: runs every 15 mins (cron)
   ├── OTA Booking Log: duplicate check & audit trail
   └── Hotel Reservation: auto-created in "Reserved" status
```

---

## 2. Setup Step-by-Step

### Step 1: Get Staging Credentials
1. Sign up for a free staging account at [staging.channex.io](https://staging.channex.io).
2. Go to **Settings > API Keys** and generate a new API key.
3. Note your **API Key**.

### Step 2: Configure OTA Settings in ERPNext
1. In ERPNext, open **Hotel Management > OTA Settings** (or type `OTA Settings` in the Awesome Bar).
2. Check **Enable OTA Integration**.
3. Set **Environment** to `Staging`.
4. Paste your **Channex API Key**.
5. Click **Save**, then click the **Test Connection** button in the header.
6. The system connects to Channex and allows you to select or enter your **Channex Property ID**.

### Step 3: Map Rooms & Rate Plans
1. Open the **Room & Rate Mapping** tab in `OTA Settings`.
2. Under **Room Type Mapping**, add rows matching each local `Hotel Room Type` to its corresponding `Channex Room Type ID`.
3. Under **Rate Plan Mapping**, map your `Room Rate Plans` to their `Channex Rate Plan IDs`.

### Step 4: Webhook & Sync Configuration
1. Open the **Webhook & Sync** tab.
2. Click **Actions > Register Webhook** (or copy the generated Webhook URL and register it in Channex).
3. The webhook URL is:
   `https://<your-site-domain>/api/method/hospitality_core.api.ota.webhook`
4. Confirm **Auto Push Availability**, **Auto Push Rates**, and **Auto Acknowledge Bookings** are checked.

---

## 3. How Bookings Work

1. **Incoming Booking**:
   - Guest books a room on MakeMyTrip / Agoda.
   - Channex immediately pushes a webhook to your ERPNext site.
   - An `OTA Booking Log` entry is created with the raw payload, OTA booking ID, channel name, guest info, and pricing.
   - ERPNext checks for duplicate booking IDs.

2. **Auto-Reservation**:
   - A `Customer` is resolved or created automatically with `is_hotel_guest = 1`.
   - A `Hotel Reservation` is created in `Reserved` status with:
     - `ota_source` (e.g. `MakeMyTrip`, `Agoda`)
     - `ota_booking_id`
     - `ota_commission`
   - The Front Desk console updates in real time with the new booking.

3. **Mandatory Acknowledgment**:
   - ERPNext automatically calls `POST /api/v1/booking_revisions/{id}/ack` so Channex knows the booking was safely recorded.

4. **Backup Pull Feed**:
   - Every 15 minutes, a background cron job (`hospitality_core.api.ota.pull_booking_revisions`) checks the feed to guarantee zero missed bookings even if internet connectivity drops temporarily.

5. **Modifications & Cancellations**:
   - If the guest changes dates or cancels on the OTA, Channex pushes an updated revision.
   - ERPNext updates the existing reservation or cancels it and frees up the room inventory.

---

## 4. Availability & Price Sync (ERPNext → Channex)

- **Availability**: When rooms are booked, checked in, checked out, or set to Out of Order, ERPNext updates inventory on Channex automatically. You can also click **Sync > Push Availability Now** anytime.
- **Rates**: When you update a `Room Rate Plan`, the new nightly rates and stop-sell rules are automatically synced to Channex.

---

## 5. Certification Checklist Before Production

Before switching Environment to `Production`:
1. [ ] Successfully received a test booking in Staging.
2. [ ] Verified the booking created a `Hotel Reservation` and `OTA Booking Log`.
3. [ ] Tested a booking modification.
4. [ ] Tested a booking cancellation.
5. [ ] Verified availability was pushed back to Channex.
6. [ ] Schedule your live screen-share certification session with the Channex support team.

