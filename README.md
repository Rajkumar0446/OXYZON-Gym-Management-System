# OXYZON GYM — Multi-Gym Owner & Member Management

## Demo owner login (for testing)
Use these credentials to try the pre-created demo gym after starting the app:

- **Owner login page:** `http://127.0.0.1:5000/owner/login`
- **Email:** `demo.owner@oxyzongym.com`
- **Password:** `Demo@12345`
- **Demo Gym:** `OXYZON Demo Fitness`
- **Member Join Code:** `DEMO-OXYZON`

The demo owner account is created automatically when the app starts with a **new, empty database**. If you already have an older `gym.db`, the demo account may not be added automatically. For a clean demo setup, stop the app, back up any data you need, then remove/rename `gym.db` and restart the app. This resets local data, so do not do this if you need to keep existing records.

**Security:** These are public demo credentials. Use them only for local testing. Before deploying or selling the software, remove/disable the demo account and set a strong private `SECRET_KEY`.

## What is included
- Each gym owner can register their own gym and receives a unique Gym Join Code.
- Owners log in separately and can only manage members and trainers belonging to their gym.
- Members register from the public member-registration page using their gym's Join Code.
- New member accounts start as **Pending**. The owner approves or rejects each request.
- Approved members can log in and see their own dashboard.
- Owners can assign Basic (30 days), Standard (90 days), or Premium (365 days) memberships.
- Owners can manage trainers, attendance, payments and progress.
- Passwords are stored as secure password hashes, not plain text.

## Run on your computer
1. Install Python 3.10 or newer.
2. Open this folder in VS Code.
3. In the terminal run:
   ```bash
   python -m venv venv
   ```
   Windows: `venv\Scripts\activate`
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
5. Start the app:
   ```bash
   python app.py
   ```
6. Open `http://127.0.0.1:5000`.

## First-time setup for a real gym owner
1. Select **Owner Registration** and create a gym owner account using the owner's own email and password.
2. Log in as that owner. Copy the Gym Join Code shown on the Owner Dashboard.
3. Share your deployed website link and that Join Code with gym members.
4. Members register with name, email, mobile, age, password and Join Code.
5. The owner opens **New Member Requests** and approves or rejects each registration.
6. After approval, assign a membership plan from the Members table.
7. The member can now log in and see their own dashboard.

## Deploying for access from any device
The local address `127.0.0.1` works only on the computer running the app. To let members register from phones or other computers, deploy this Flask app to a hosting provider and share its public HTTPS URL.

This project uses SQLite. If deploying on Render, use a persistent disk and set:
- `DB_PATH=/var/data/gym.db`
- `SECRET_KEY` to a long random secret value
- Start command: `gunicorn app:app`

A `render.yaml` example is included. Keep the persistent disk attached; otherwise SQLite data can be lost when the service is redeployed. For a larger commercial service with many gyms, use a managed PostgreSQL database and review security, backups, privacy and payment handling before launch.

## Important
- This is a starter/demo application, not a fully audited commercial SaaS product.
- Use HTTPS in production, set a private `SECRET_KEY`, enable backups, and test access controls before selling it.
- Do not collect card details in this app. Record payment status only; use a trusted payment gateway if online payments are needed.
