# Master Developer & Operations Guide: Sick Bed Services (QuickNest)

Welcome to the **Sick Bed Services (QuickNest)** codebase guide. This document serves as the master guide for developers, system administrators, and operations teams to set up, run, test, and maintain the project.

---

## 1. Project Overview & Architecture

**Sick Bed Services** (under *Kutch Yuvak Sangh, Bhayandar*) is a medical equipment rental web application. It allows customers to book medical equipment (beds, oxygen cylinders, wheelchairs, walkers, etc.) on a daily rental basis.

### Core Tech Stack
- **Framework**: Django 5.2.4 (Python 3.x)
- **Database**: PostgreSQL (hosted on Supabase)
- **Payments**: Razorpay Gateway (for online checkouts)
- **PDF Generation**: ReportLab (receipt PDFs) & html2pdf.js (UI PDF downloads)
- **Authentication**: Custom Django Authentication + Google OAuth2 (via `social-auth-app-django`)
- **Styling**: Vanilla CSS, FontAwesome, Google Fonts (Outfit, Inter)

---

## 2. Codebase Directory Structure

```text
QuickNest/
│
├── myenv/                      # Local Python Virtual Environment
│
└── rental/                     # Django Project Directory
    ├── manage.py               # Django Command Line Utility
    ├── requirements.txt        # Python Packages/Dependencies
    ├── .env                    # Local Environment Configuration File
    │
    ├── rental/                 # Main Project Configuration
    │   ├── settings.py         # Global Django Settings
    │   ├── urls.py             # Root Routing Configuration
    │   └── wsgi.py / asgi.py   # Web Servers Interfaces
    │
    ├── app/                    # Primary Application Logic
    │   ├── models.py           # Database Schemas (History, Inventory, Payment, etc.)
    │   ├── views.py            # HTTP Requests / Controller Handlers
    │   ├── urls.py             # Sub-routing Configuration
    │   ├── utils.py            # Email Notifications, PDF and Helper Utilities
    │   ├── signals.py          # Django Signals (Auto-notifications on stock availability)
    │   ├── tests.py            # Unit and Integration Tests Suite
    │   ├── static/             # CSS Styles, Images, Logos, and JS scripts
    │   └── templates/          # HTML Templates (base, items, return_receipt, success, etc.)
    │
    └── media/                  # Media Uploads (User ID Proof Files, etc.)
```

---

## 3. Local Setup & Installation

### Step 1: Clone and Create Virtual Environment
1. Navigate to the project root:
   ```bash
   cd QuickNest
   ```
2. Create and activate a virtual environment:
   * **Windows (PowerShell)**:
     ```powershell
     python -m venv myenv
     .\myenv\Scripts\Activate.ps1
     ```
   * **Linux/macOS**:
     ```bash
     python3 -m venv myenv
     source myenv/bin/activate
     ```

### Step 2: Install Dependencies
Run the package manager installation:
```bash
pip install -r rental/requirements.txt
```

### Step 3: Set Up Environment Variables (`.env`)
Create a `.env` file inside the `rental/` directory with the following keys:
```ini
DJANGO_SECRET_KEY=your-django-secret-key
DJANGO_DEBUG=True

# Supabase / PostgreSQL Credentials
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=your-database-password
DB_HOST=your-supabase-db-host
DB_PORT=5432

# Google OAuth2 Authentication Details
SOCIAL_AUTH_GOOGLE_OAUTH2_KEY=your-google-oauth2-client-id
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET=your-google-oauth2-client-secret

# Razorpay Payment Gateway Keys
RAZORPAY_API_KEY=your-razorpay-api-key
RAZORPAY_API_SECRET=your-razorpay-api-secret

# Mailing / Notification Configuration
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=bhayander@kutchyuvaksangh.org
EMAIL_HOST_PASSWORD=your-email-host-app-password
DEFAULT_FROM_EMAIL=bhayander@kutchyuvaksangh.org
ADMIN_EMAIL=bhayander@kutchyuvaksangh.org
```

### Step 4: Run Migrations & Start Server
1. Navigate to the Django root:
   ```bash
   cd rental
   ```
2. Run database migrations:
   ```bash
   python manage.py migrate
   ```
3. Run the development server:
   ```bash
   python manage.py runserver
   ```
4. Access the portal at `http://localhost:8000/`.

---

## 4. Database Setup & Migrations

### Model Architecture
- **`Inventory`**: Stores medical equipment, pricing rules, daily rental rates, deposits, stock tracking columns (`total_quantity`, `available_quantity`, `booked_quantity`).
- **`History`**: The master ledger representing rental orders. Stores transaction information, dates, renter credentials, delivery choices, and order status (`pending`, `approved`, `returned`, `cancelled`).
- **`BookingExtension`**: Holds details about return date extensions, additional charges, and extra days.
- **`Payment`**: Records individual transaction references, amounts, payment gateway transaction IDs, and receipt documents.
- **`UserDetail`**: Caches normal user metadata (phone, address, pincode, patient name, and uploaded ID proofs).
- **`NotifyRequest`**: Manages waitlist alerts for out-of-stock items.

### Creating Schema Changes
If models are updated, run:
```bash
python manage.py makemigrations
python manage.py migrate
```

---

## 5. Core Workflows & Logic

### 🛒 A. Rent Checkout Flow
To avoid premature order creation and cart deletion for normal users, the checkout flow utilizes a unified session-based design:
1. **Cart View (`cart_view`)**: The user selects items, rental dates, quantities, and views totals.
2. **User Details (`userdetail`)**:
   - The user inputs phone, address, pincode, patient name, and uploads an ID proof (PNG, JPG, or PDF under 5 MB).
   - If they are a normal user (non-superuser), details are persisted to the `UserDetail` table.
   - **Crucial**: The details are saved in the `request.session` object, keeping the `Cart` intact.
3. **Delivery Selection (`select_delivery`)**: Saves selected delivery option (Take Away vs Home Delivery) and associated delivery charge directly to the session.
4. **Payment Method (`paymentmethod`)**:
   - Inspects the session values and builds the `History` database records.
   - Triggers the `"New Booking Created"` notification via `send_notification()`.
   - Clears the database `Cart`.
   - Re-routes the user to online gateway checkout (Razorpay) or displays the COD success summary.

### 📅 B. Rental Extension Flow
When a user or staff member extends a return date:
1. They access `extend-return/<str:order_id>/` which invokes `extend_return_date()`.
2. Selects a new return date (must be after the current billing end date).
3. A `BookingExtension` record is created, tracking the additional rent amount (`price_per_day * quantity * extra_days`).
4. The `extended_end_date` property on the `History` record is updated.
5. The system deletes the old receipt and generates an updated booking receipt PDF.
6. A notification of type `'return'` is dispatched using `send_notification()`, which emails the confirmation to the customer and CCs the administrator.

### 🔄 C. Return & Refund Flow
When equipment is returned:
1. Staff or admin starts the return flow via `return_order()` or `approve_return_order()`.
2. The user can request to donate their deposit partial/fully, which updates `donation_amount` and `donation_comment`.
3. Upon approval:
   - `is_returned` is marked `True`.
   - Inventory items have `booked_quantity` decremented and `available_quantity` incremented.
   - A PDF/HTML Return Receipt is generated containing full item lists, delivery options, pickup charges, donation sums, and the final computed refund amount.
   - The customer is greeted as `"Dear customer,"` and notified that the return was successfully processed.

### ✉️ D. Email Notifications System
- **Function**: `send_notification()` in `app/utils.py` handles email dispatch.
- **Renter vs Admin logic**: If the type is `'booking'`, `'payment'`, or `'return'`, the renter receives an email copy, while the admin (`ADMIN_EMAIL`) is CC'd.
- **Template overrides**: If the user is a non-superuser, the email greeting is standardized to `"Dear customer,"` rather than using their username/account name.

---

## 6. Running Tests

Automated testing is configured using Django's TestCase class. The suite covers:
- User details submission and session management.
- Custom notification message templates for bookings, returns, and extensions.
- Admin approval pathways.
- Email dispatch and PDF receipt generation correctness.

To run tests:
```bash
python manage.py test
```

---

## 7. Troubleshooting & Common Issues

- **Emails are not sending**: Check the `EMAIL_BACKEND` configuration in `settings.py`. Ensure Gmail App Passwords (if using Google SMTP) or provider configurations are updated.
- **Razorpay Checkout Fails**: Verify `RAZORPAY_API_KEY` and `RAZORPAY_API_SECRET` are correctly exported in the active `.env` file.
- **Supabase Database Connection Issues**: Ensure your IP address is not blocked by firewalls and check that `DB_HOST`, `DB_USER`, and `DB_PASSWORD` are valid.
- **No static styles rendering**: Run `python manage.py collectstatic` to gather static assets into the configured root folder.
