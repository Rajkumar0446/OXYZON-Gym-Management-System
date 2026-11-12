from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, make_response
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from functools import wraps
from datetime import datetime, date, timedelta
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os
import secrets

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.secret_key = os.environ.get("SECRET_KEY", "oxyzon-demo-change-this-secret-key")
DB = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "gym.db"))
PDF_FONT_PATH = os.path.join(BASE_DIR, "static", "fonts", "DejaVuSans.ttf")
pdfmetrics.registerFont(TTFont("DejaVuSans", PDF_FONT_PATH))


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS gyms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        join_code TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'member',
        created_at TEXT NOT NULL,
        gym_id INTEGER,
        trainer_id INTEGER,
        mobile TEXT,
        age INTEGER,
        approval_status TEXT NOT NULL DEFAULT 'approved',
        FOREIGN KEY(trainer_id) REFERENCES trainers(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS memberships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        plan TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Active',
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS workouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        day TEXT NOT NULL,
        details TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS diet_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        goal TEXT NOT NULL,
        calories INTEGER NOT NULL,
        meals TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS trainers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        specialization TEXT,
        created_at TEXT NOT NULL,
        gym_id INTEGER
    );

    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        attendance_date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Present',
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, attendance_date)
    );

    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        payment_date TEXT NOT NULL,
        method TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Paid',
        note TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        record_date TEXT NOT NULL,
        weight REAL,
        body_fat REAL,
        note TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # Migrate older single-gym databases to the multi-gym structure.
    user_columns = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "gym_id" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN gym_id INTEGER")
    trainer_columns = [r[1] for r in conn.execute("PRAGMA table_info(trainers)").fetchall()]
    if "gym_id" not in trainer_columns:
        conn.execute("ALTER TABLE trainers ADD COLUMN gym_id INTEGER")

    # Existing databases from the first version need this column.
    columns = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "trainer_id" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN trainer_id INTEGER")
    # Member profile and owner-approval fields for multi-gym registration.
    if "mobile" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN mobile TEXT")
    if "age" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN age INTEGER")
    if "approval_status" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'approved'")

    # Keep the previous demo admin working as an owner of a demo gym.
    legacy = conn.execute("SELECT * FROM users WHERE email=?", ("admin@gym.com",)).fetchone()
    if legacy and not legacy["gym_id"]:
        code = "DEMO-OXYZON"
        conn.execute("INSERT OR IGNORE INTO gyms(name,join_code,created_at) VALUES(?,?,?)",
                      ("OXYZON Demo Gym", code, datetime.now().isoformat(timespec="seconds")))
        gym = conn.execute("SELECT id FROM gyms WHERE join_code=?", (code,)).fetchone()
        conn.execute("UPDATE users SET role='owner', gym_id=? WHERE id=?", (gym["id"], legacy["id"]))

    # Create a clearly labelled demo owner on a fresh database so the project
    # can be tested immediately. Real gym owners should register their own account.
    owner_count = conn.execute("SELECT COUNT(*) FROM users WHERE role IN ('owner','admin')").fetchone()[0]
    if owner_count == 0:
        demo_code = "DEMO-OXYZON"
        conn.execute("INSERT OR IGNORE INTO gyms(name,join_code,created_at) VALUES(?,?,?)",
                     ("OXYZON Demo Fitness", demo_code, datetime.now().isoformat(timespec="seconds")))
        demo_gym = conn.execute("SELECT id FROM gyms WHERE join_code=?", (demo_code,)).fetchone()
        conn.execute(
            "INSERT INTO users(name,email,password,role,created_at,gym_id) VALUES(?,?,?,?,?,?)",
            ("Demo Owner", "demo.owner@oxyzongym.com", generate_password_hash("Demo@12345"),
             "owner", datetime.now().isoformat(timespec="seconds"), demo_gym["id"])
        )
    conn.commit()
    conn.close()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") not in ("owner", "admin"):
            flash("Owner access required.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/owner/register", methods=["GET", "POST"])
def owner_register():
    if request.method == "POST":
        gym_name = request.form.get("gym_name", "").strip()
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not all([gym_name, name, email]) or len(password) < 8:
            flash("Fill all fields. Password must be at least 8 characters.", "error")
            return redirect(url_for("owner_register"))
        code = "GYM-" + secrets.token_hex(3).upper()
        conn = get_db()
        try:
            cur = conn.execute("INSERT INTO gyms(name,join_code,created_at) VALUES(?,?,?)",
                               (gym_name, code, datetime.now().isoformat(timespec="seconds")))
            gym_id = cur.lastrowid
            conn.execute("INSERT INTO users(name,email,password,role,created_at,gym_id) VALUES(?,?,?,?,?,?)",
                         (name, email, generate_password_hash(password), "owner",
                          datetime.now().isoformat(timespec="seconds"), gym_id))
            conn.commit()
            flash(f"Gym created! Your Member Join Code is {code}. Save it and share it with your members.", "success")
            return redirect(url_for("owner_login"))
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("This email is already registered. Please use another email or login.", "error")
        finally:
            conn.close()
    return render_template("owner_register.html")


@app.route("/owner/login", methods=["GET", "POST"])
def owner_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=? AND role IN ('owner','admin')", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = "owner"
            session["gym_id"] = user["gym_id"]
            return redirect(url_for("admin"))
        flash("Invalid owner email or password.", "error")
    return render_template("owner_login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        gym_code = request.form.get("gym_code", "").strip().upper()
        mobile = request.form.get("mobile", "").strip()
        age_text = request.form.get("age", "").strip()
        try:
            age = int(age_text) if age_text else None
        except ValueError:
            age = None
        if not name or not email or len(password) < 8 or not gym_code or not mobile or age is None or age < 13 or age > 100:
            flash("Enter all details, valid age (13–100), Gym Join Code and a password of at least 8 characters.", "error")
            return redirect(url_for("register"))
        conn = get_db()
        try:
            gym = conn.execute("SELECT id FROM gyms WHERE join_code=?", (gym_code,)).fetchone()
            if not gym:
                flash("Invalid Gym Join Code. Please ask your gym owner.", "error")
                return redirect(url_for("register"))
            conn.execute(
                "INSERT INTO users(name,email,password,role,created_at,gym_id,mobile,age,approval_status) VALUES(?,?,?,?,?,?,?,?,?)",
                (name, email, generate_password_hash(password), "member",
                 datetime.now().isoformat(timespec="seconds"), gym["id"], mobile, age, "pending")
            )
            conn.commit()
            flash("Registration submitted. Please wait for your gym owner to approve your account.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already registered.", "error")
            return redirect(url_for("register"))
        finally:
            conn.close()
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            if user["role"] == "member" and user["approval_status"] != "approved":
                flash("Your registration is waiting for owner approval. Please try again later.", "error")
                return render_template("login.html")
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            session["gym_id"] = user["gym_id"]
            return redirect(url_for("admin") if user["role"] in ("owner", "admin") else url_for("dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    if session.get("role") in ("owner", "admin"):
        return redirect(url_for("admin"))
    conn = get_db()
    user = conn.execute("""
        SELECT u.id,u.name,u.email,u.role,u.created_at,u.trainer_id,
               t.name AS trainer_name,t.specialization AS trainer_specialization
        FROM users u LEFT JOIN trainers t ON t.id=u.trainer_id
        WHERE u.id=?
    """, (session["user_id"],)).fetchone()
    membership = conn.execute(
        "SELECT * FROM memberships WHERE user_id=? ORDER BY id DESC LIMIT 1", (session["user_id"],)
    ).fetchone()
    workouts = conn.execute(
        "SELECT * FROM workouts WHERE user_id=? ORDER BY id DESC", (session["user_id"],)
    ).fetchall()
    diet = conn.execute(
        "SELECT * FROM diet_plans WHERE user_id=? ORDER BY id DESC LIMIT 1", (session["user_id"],)
    ).fetchone()
    attendance = conn.execute(
        "SELECT * FROM attendance WHERE user_id=? ORDER BY attendance_date DESC LIMIT 10", (session["user_id"],)
    ).fetchall()
    payments = conn.execute(
        "SELECT * FROM payments WHERE user_id=? ORDER BY payment_date DESC, id DESC LIMIT 10", (session["user_id"],)
    ).fetchall()
    progress = conn.execute(
        "SELECT * FROM progress WHERE user_id=? ORDER BY record_date DESC, id DESC LIMIT 10", (session["user_id"],)
    ).fetchall()
    attendance_count = conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE user_id=? AND status='Present'", (session["user_id"],)
    ).fetchone()[0]
    total_paid = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM payments WHERE user_id=? AND status='Paid'", (session["user_id"],)
    ).fetchone()[0]
    conn.close()
    return render_template("dashboard.html", user=user, membership=membership, workouts=workouts,
                           diet=diet, attendance=attendance, payments=payments, progress=progress,
                           attendance_count=attendance_count, total_paid=total_paid)


@app.route("/membership", methods=["POST"])
@login_required
def membership():
    # Memberships are assigned by the gym owner, not self-selected by members.
    if session.get("role") not in ("owner", "admin"):
        flash("Your gym owner assigns membership plans. Please contact them.", "error")
        return redirect(url_for("dashboard"))
    plan = request.form["plan"]
    plans = {"Basic": 30, "Standard": 90, "Premium": 365}
    if plan not in plans:
        flash("Invalid membership plan.", "error")
        return redirect(url_for("dashboard"))
    start = date.today()
    end = start + timedelta(days=plans[plan])
    conn = get_db()
    conn.execute("INSERT INTO memberships(user_id,plan,start_date,end_date,status) VALUES(?,?,?,?,?)",
                 (session["user_id"], plan, start.isoformat(), end.isoformat(), "Active"))
    conn.commit()
    conn.close()
    flash("Membership added successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/api/bmi", methods=["POST"])
def bmi():
    data = request.get_json(silent=True) or {}
    try:
        height = float(data["height"]) / 100
        weight = float(data["weight"])
        if height <= 0 or weight <= 0:
            raise ValueError
        value = weight / (height * height)
        if value < 18.5:
            category = "Underweight"
        elif value < 25:
            category = "Normal"
        elif value < 30:
            category = "Overweight"
        else:
            category = "Obesity"
        return jsonify({"bmi": round(value, 1), "category": category})
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "Enter valid height and weight."}), 400


@app.route("/api/workout", methods=["POST"])
@login_required
def workout():
    goal = (request.get_json(silent=True) or {}).get("goal", "fitness")
    plans = {
        "muscle": [("Monday", "Chest + Triceps", "Bench press, incline press, push-ups, triceps extensions"),
                   ("Wednesday", "Back + Biceps", "Lat pulldown, rows, pull-ups, curls"),
                   ("Friday", "Legs + Shoulders", "Squats, lunges, shoulder press, lateral raises")],
        "weightloss": [("Monday", "Full Body", "Squats, push-ups, rows + 20 min brisk walk"),
                       ("Wednesday", "Cardio", "Cycling or jogging + core exercises"),
                       ("Friday", "Full Body", "Lunges, presses, rows + 20 min brisk walk")],
        "fitness": [("Monday", "Full Body", "Squats, push-ups, rows, plank"),
                    ("Wednesday", "Cardio + Core", "20–30 min cardio + crunches + plank"),
                    ("Friday", "Full Body", "Lunges, shoulder press, rows, mountain climbers")]
    }
    selected = plans.get(goal, plans["fitness"])
    conn = get_db()
    conn.execute("DELETE FROM workouts WHERE user_id=?", (session["user_id"],))
    for day, title, details in selected:
        conn.execute("INSERT INTO workouts(user_id,title,day,details) VALUES(?,?,?,?)",
                     (session["user_id"], title, day, details))
    conn.commit()
    conn.close()
    return jsonify({"message": "Workout plan saved.", "plan": selected})


@app.route("/api/diet", methods=["POST"])
@login_required
def diet():
    goal = (request.get_json(silent=True) or {}).get("goal", "fitness")
    plans = {
        "muscle": (2800, "Breakfast: eggs + oats | Lunch: rice + chicken/paneer + vegetables | Snack: fruit + nuts | Dinner: roti + protein + salad"),
        "weightloss": (1900, "Breakfast: oats + fruit | Lunch: rice/roti + vegetables + protein | Snack: fruit/curd | Dinner: soup + salad + protein"),
        "fitness": (2300, "Breakfast: eggs/oats + fruit | Lunch: balanced rice/roti + protein + vegetables | Snack: nuts + fruit | Dinner: roti + protein + vegetables")
    }
    calories, meals = plans.get(goal, plans["fitness"])
    conn = get_db()
    conn.execute("DELETE FROM diet_plans WHERE user_id=?", (session["user_id"],))
    conn.execute("INSERT INTO diet_plans(user_id,goal,calories,meals) VALUES(?,?,?,?)",
                 (session["user_id"], goal, calories, meals))
    conn.commit()
    conn.close()
    return jsonify({"message": "Diet plan saved.", "calories": calories, "meals": meals})


# ---------------- Admin ----------------
@app.route("/admin")
@login_required
@admin_required
def admin():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "all").strip()
    conn = get_db()
    where = ["u.role='member'", "u.gym_id=?", "u.approval_status='approved'"]
    params = [session.get("gym_id")]
    if q:
        where.append("(u.name LIKE ? OR u.email LIKE ? OR CAST(u.id AS TEXT) LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    if status == "active":
        where.append("m.status='Active' AND m.end_date >= date('now')")
    elif status == "expired":
        where.append("(m.end_date < date('now') OR m.end_date IS NULL)")

    users = conn.execute(f"""
        SELECT u.id,u.name,u.email,u.created_at,u.trainer_id,
               t.name AS trainer_name,
               m.plan,m.start_date,m.end_date,m.status,
               COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.user_id=u.id AND p.status='Paid'),0) AS total_paid,
               COALESCE((SELECT COUNT(*) FROM attendance a WHERE a.user_id=u.id AND a.status='Present'),0) AS present_count,
               (SELECT pr.weight FROM progress pr WHERE pr.user_id=u.id ORDER BY pr.record_date DESC, pr.id DESC LIMIT 1) AS latest_weight
        FROM users u
        LEFT JOIN trainers t ON t.id=u.trainer_id
        LEFT JOIN memberships m ON m.id=(SELECT id FROM memberships WHERE user_id=u.id ORDER BY id DESC LIMIT 1)
        WHERE {' AND '.join(where)}
        ORDER BY u.id DESC
    """, params).fetchall()

    trainers = conn.execute("SELECT * FROM trainers WHERE gym_id=? ORDER BY name", (session.get("gym_id"),)).fetchall()
    pending_members = conn.execute("SELECT id,name,email,mobile,age,created_at FROM users WHERE role='member' AND gym_id=? AND approval_status='pending' ORDER BY id DESC", (session.get("gym_id"),)).fetchall()
    stats = {
        "members": conn.execute("SELECT COUNT(*) FROM users WHERE role='member' AND gym_id=? AND approval_status='approved'", (session.get("gym_id"),)).fetchone()[0],
        "active": conn.execute("SELECT COUNT(*) FROM memberships m JOIN users u ON u.id=m.user_id WHERE u.role='member' AND u.gym_id=? AND m.id=(SELECT id FROM memberships WHERE user_id=u.id ORDER BY id DESC LIMIT 1) AND m.status='Active' AND m.end_date>=date('now')", (session.get("gym_id"),)).fetchone()[0],
        "trainers": conn.execute("SELECT COUNT(*) FROM trainers WHERE gym_id=?", (session.get("gym_id"),)).fetchone()[0],
        "revenue": conn.execute("SELECT COALESCE(SUM(p.amount),0) FROM payments p JOIN users u ON u.id=p.user_id WHERE p.status='Paid' AND u.gym_id=?", (session.get("gym_id"),)).fetchone()[0],
        "attendance": conn.execute("SELECT COUNT(*) FROM attendance a JOIN users u ON u.id=a.user_id WHERE a.status='Present' AND a.attendance_date=date('now') AND u.gym_id=?", (session.get("gym_id"),)).fetchone()[0],
    }
    gym = conn.execute("SELECT name,join_code FROM gyms WHERE id=?", (session.get("gym_id"),)).fetchone()
    conn.close()
    return render_template("admin.html", users=users, trainers=trainers, pending_members=pending_members, stats=stats, q=q, status=status, gym=gym)


@app.route("/admin/member/<int:user_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_member(user_id):
    conn = get_db()
    cur = conn.execute("UPDATE users SET approval_status='approved' WHERE id=? AND role='member' AND gym_id=? AND approval_status='pending'", (user_id, session.get("gym_id")))
    conn.commit()
    conn.close()
    flash("Member approved. You can now assign a membership plan.", "success" if cur.rowcount else "Member request not found.")
    return redirect(url_for("admin"))


@app.route("/admin/member/<int:user_id>/reject", methods=["POST"])
@login_required
@admin_required
def reject_member(user_id):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id=? AND role='member' AND gym_id=? AND approval_status='pending'", (user_id, session.get("gym_id")))
    conn.commit()
    conn.close()
    flash("Pending member request rejected.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/member/<int:user_id>/membership", methods=["POST"])
@login_required
@admin_required
def assign_membership(user_id):
    plan = request.form.get("plan", "")
    plans = {"Basic": 30, "Standard": 90, "Premium": 365}
    if plan not in plans:
        flash("Choose a valid membership plan.", "error")
        return redirect(url_for("admin"))
    start = date.fromisoformat(request.form.get("start_date") or date.today().isoformat())
    end = start + timedelta(days=plans[plan])
    conn = get_db()
    member = conn.execute("SELECT id FROM users WHERE id=? AND role='member' AND gym_id=? AND approval_status='approved'", (user_id, session.get("gym_id"))).fetchone()
    if not member:
        conn.close()
        flash("Approved member not found in your gym.", "error")
        return redirect(url_for("admin"))
    conn.execute("INSERT INTO memberships(user_id,plan,start_date,end_date,status) VALUES(?,?,?,?, 'Active')", (user_id, plan, start.isoformat(), end.isoformat()))
    conn.commit()
    conn.close()
    flash(f"{plan} membership assigned successfully.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/member/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_member(user_id):
    conn = get_db()
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        trainer_id = request.form.get("trainer_id") or None
        if trainer_id:
            valid_trainer = conn.execute("SELECT id FROM trainers WHERE id=? AND gym_id=?", (trainer_id, session.get("gym_id"))).fetchone()
            if not valid_trainer:
                conn.close()
                flash("Selected trainer does not belong to your gym.", "error")
                return redirect(url_for("admin"))
        try:
            conn.execute("UPDATE users SET name=?, email=?, trainer_id=? WHERE id=? AND role='member' AND gym_id=?",
                         (name, email, trainer_id, user_id, session.get("gym_id")))
            conn.commit()
            flash("Member updated successfully.", "success")
        except sqlite3.IntegrityError:
            flash("That email is already registered.", "error")
        finally:
            conn.close()
        return redirect(url_for("admin"))
    user = conn.execute("SELECT * FROM users WHERE id=? AND role='member' AND gym_id=?", (user_id, session.get("gym_id"))).fetchone()
    trainers = conn.execute("SELECT * FROM trainers WHERE gym_id=? ORDER BY name", (session.get("gym_id"),)).fetchall()
    conn.close()
    if not user:
        flash("Member not found.", "error")
        return redirect(url_for("admin"))
    return render_template("edit_member.html", user=user, trainers=trainers)


@app.route("/admin/delete/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id=? AND role='member' AND gym_id=?", (user_id, session.get("gym_id")))
    conn.commit()
    conn.close()
    flash("Member and related records deleted.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/member/<int:user_id>/assign-trainer", methods=["POST"])
@login_required
@admin_required
def assign_trainer(user_id):
    trainer_id = request.form.get("trainer_id") or None
    conn = get_db()
    member = conn.execute("SELECT id FROM users WHERE id=? AND role='member' AND gym_id=?", (user_id, session.get("gym_id"))).fetchone()
    if not member:
        conn.close()
        flash("Member not found.", "error")
        return redirect(url_for("admin"))

    if trainer_id is not None:
        trainer = conn.execute("SELECT id FROM trainers WHERE id=? AND gym_id=?", (trainer_id, session.get("gym_id"))).fetchone()
        if not trainer:
            conn.close()
            flash("Selected trainer was not found.", "error")
            return redirect(url_for("admin"))
        trainer_id = int(trainer_id)

    conn.execute("UPDATE users SET trainer_id=? WHERE id=? AND role='member' AND gym_id=?", (trainer_id, user_id, session.get("gym_id")))
    conn.commit()
    conn.close()
    flash("Trainer assigned successfully." if trainer_id else "Trainer assignment removed.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/trainer/add", methods=["POST"])
@login_required
@admin_required
def add_trainer():
    name = request.form["name"].strip()
    if not name:
        flash("Trainer name is required.", "error")
        return redirect(url_for("admin"))
    conn = get_db()
    conn.execute("INSERT INTO trainers(name,email,phone,specialization,created_at,gym_id) VALUES(?,?,?,?,?,?)",
                 (name, request.form.get("email", "").strip(), request.form.get("phone", "").strip(),
                  request.form.get("specialization", "").strip(), datetime.now().isoformat(timespec="seconds"), session.get("gym_id")))
    conn.commit()
    conn.close()
    flash("Trainer added.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/trainer/delete/<int:trainer_id>", methods=["POST"])
@login_required
@admin_required
def delete_trainer(trainer_id):
    conn = get_db()
    conn.execute("UPDATE users SET trainer_id=NULL WHERE trainer_id=? AND gym_id=?", (trainer_id, session.get("gym_id")))
    conn.execute("DELETE FROM trainers WHERE id=? AND gym_id=?", (trainer_id, session.get("gym_id")))
    conn.commit()
    conn.close()
    flash("Trainer deleted.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/attendance", methods=["POST"])
@login_required
@admin_required
def add_attendance():
    user_id = request.form.get("user_id")
    attendance_date = request.form.get("attendance_date") or date.today().isoformat()
    status = request.form.get("status", "Present")
    conn = get_db()
    valid_member = conn.execute("SELECT id FROM users WHERE id=? AND gym_id=? AND role='member'", (user_id, session.get("gym_id"))).fetchone()
    if not valid_member:
        conn.close(); flash("Member not found in your gym.", "error"); return redirect(url_for("admin"))
    conn.execute("""
        INSERT INTO attendance(user_id,attendance_date,status) VALUES(?,?,?)
        ON CONFLICT(user_id,attendance_date) DO UPDATE SET status=excluded.status
    """, (user_id, attendance_date, status))
    conn.commit()
    conn.close()
    flash("Attendance saved.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/payment", methods=["POST"])
@login_required
@admin_required
def add_payment():
    try:
        amount = float(request.form["amount"])
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        flash("Enter a valid payment amount.", "error")
        return redirect(url_for("admin"))
    conn = get_db()
    valid_member = conn.execute("SELECT id FROM users WHERE id=? AND gym_id=? AND role='member'", (request.form["user_id"], session.get("gym_id"))).fetchone()
    if not valid_member:
        conn.close(); flash("Member not found in your gym.", "error"); return redirect(url_for("admin"))
    conn.execute("INSERT INTO payments(user_id,amount,payment_date,method,status,note) VALUES(?,?,?,?,?,?)",
                 (request.form["user_id"], amount, request.form.get("payment_date") or date.today().isoformat(),
                  request.form.get("method", "Cash"), request.form.get("status", "Paid"), request.form.get("note", "").strip()))
    conn.commit()
    conn.close()
    flash("Payment recorded.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/progress", methods=["POST"])
@login_required
@admin_required
def add_progress():
    def num(name):
        value = request.form.get(name, "").strip()
        return float(value) if value else None
    try:
        weight = num("weight")
        body_fat = num("body_fat")
    except ValueError:
        flash("Weight/body fat must be numbers.", "error")
        return redirect(url_for("admin"))
    conn = get_db()
    valid_member = conn.execute("SELECT id FROM users WHERE id=? AND gym_id=? AND role='member'", (request.form["user_id"], session.get("gym_id"))).fetchone()
    if not valid_member:
        conn.close(); flash("Member not found in your gym.", "error"); return redirect(url_for("admin"))
    conn.execute("INSERT INTO progress(user_id,record_date,weight,body_fat,note) VALUES(?,?,?,?,?)",
                 (request.form["user_id"], request.form.get("record_date") or date.today().isoformat(),
                  weight, body_fat, request.form.get("note", "").strip()))
    conn.commit()
    conn.close()
    flash("Progress saved.", "success")
    return redirect(url_for("admin"))



def pdf_response(title, rows, filename):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    styles["Title"].fontName = "DejaVuSans"
    styles["Heading2"].fontName = "DejaVuSans"
    styles["Heading3"].fontName = "DejaVuSans"
    styles["BodyText"].fontName = "DejaVuSans"
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontName="DejaVuSans", fontSize=9, leading=12))
    story = [Paragraph("OXYZON GYM Management System", styles["Title"]),
             Paragraph(title, styles["Heading2"]), Spacer(1, 12)]
    for label, value in rows:
        story.append(Paragraph(f"<b>{label}:</b> {value if value not in (None, '') else '—'}", styles["BodyText"]))
        story.append(Spacer(1, 6))
    doc.build(story)
    response = make_response(buffer.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@app.route("/payment/<int:payment_id>/pdf")
@login_required
def payment_pdf(payment_id):
    conn = get_db()
    payment = conn.execute("""
        SELECT p.*, u.name, u.email, u.gym_id FROM payments p
        JOIN users u ON u.id=p.user_id WHERE p.id=?
    """, (payment_id,)).fetchone()
    conn.close()
    if not payment or (session.get("role") not in ("admin", "owner") and payment["user_id"] != session["user_id"]) or (session.get("role") in ("admin", "owner") and payment["gym_id"] != session.get("gym_id")):
        flash("Payment record not found or access denied.", "error")
        return redirect(url_for("dashboard"))
    rows = [
        ("Receipt ID", f"PAY-{payment['id']:05d}"),
        ("Member", payment["name"]),
        ("Email", payment["email"]),
        ("Amount", f"₹{payment['amount']:.2f}"),
        ("Payment Date", payment["payment_date"]),
        ("Payment Method", payment["method"]),
        ("Status", payment["status"]),
        ("Note", payment["note"] or "—"),
    ]
    return pdf_response("Payment Receipt", rows, f"OXYZON_Payment_{payment['id']}.pdf")


@app.route("/member/<int:user_id>/pdf")
@admin_required
def member_pdf(user_id):
    conn = get_db()
    user = conn.execute("""
        SELECT u.id,u.name,u.email,u.created_at,t.name AS trainer_name,
               t.specialization AS trainer_specialization
        FROM users u LEFT JOIN trainers t ON t.id=u.trainer_id
        WHERE u.id=? AND u.role='member' AND u.gym_id=?
    """, (user_id, session.get("gym_id"))).fetchone()
    membership = conn.execute("SELECT * FROM memberships WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    total_paid = conn.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE user_id=? AND status='Paid'", (user_id,)).fetchone()[0]
    present = conn.execute("SELECT COUNT(*) FROM attendance WHERE user_id=? AND status='Present'", (user_id,)).fetchone()[0]
    progress = conn.execute("SELECT record_date,weight,body_fat,note FROM progress WHERE user_id=? ORDER BY record_date DESC,id DESC LIMIT 10", (user_id,)).fetchall()
    payments = conn.execute("SELECT payment_date,amount,method,status FROM payments WHERE user_id=? ORDER BY payment_date DESC,id DESC LIMIT 10", (user_id,)).fetchall()
    conn.close()
    if not user:
        flash("Member not found.", "error")
        return redirect(url_for("admin"))
    rows = [
        ("Member ID", f"#{user['id']}"), ("Name", user["name"]), ("Email", user["email"]),
        ("Trainer", user["trainer_name"] or "Not assigned"),
        ("Specialization", user["trainer_specialization"] or "—"),
        ("Membership", membership["plan"] if membership else "No plan"),
        ("Membership End Date", membership["end_date"] if membership else "—"),
        ("Present Attendance", present), ("Total Paid", f"₹{total_paid:.2f}"),
    ]
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    styles["Title"].fontName = "DejaVuSans"
    styles["Heading2"].fontName = "DejaVuSans"
    styles["Heading3"].fontName = "DejaVuSans"
    styles["BodyText"].fontName = "DejaVuSans"
    story=[Paragraph("OXYZON GYM Management System", styles["Title"]), Paragraph("Member Data Report", styles["Heading2"]), Spacer(1,10)]
    data=[[str(k), str(v if v not in (None,'') else '—')] for k,v in rows]
    table=Table(data, colWidths=[170,330])
    table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(0,-1),colors.whitesmoke),('FONTNAME',(0,0),(-1,-1),'DejaVuSans'),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),7)]))
    story += [table, Spacer(1,16), Paragraph("Recent Payments", styles["Heading3"])]
    pay_data=[["Date","Amount","Method","Status"]] + [[p['payment_date'], f"₹{p['amount']:.2f}", p['method'], p['status']] for p in payments]
    pt=Table(pay_data, colWidths=[100,100,120,100], repeatRows=1)
    pt.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.lightgrey),('FONTNAME',(0,0),(-1,-1),'DejaVuSans'),('PADDING',(0,0),(-1,-1),6)]))
    story += [pt, Spacer(1,16), Paragraph("Recent Progress", styles["Heading3"])]
    prog_data=[["Date","Weight kg","Body Fat %","Note"]] + [[p['record_date'], p['weight'] or '—', p['body_fat'] or '—', p['note'] or '—'] for p in progress]
    gt=Table(prog_data, colWidths=[90,90,90,150], repeatRows=1)
    gt.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.lightgrey),('FONTNAME',(0,0),(-1,-1),'DejaVuSans'),('PADDING',(0,0),(-1,-1),6)]))
    story += [gt]
    doc.build(story)
    response=make_response(buffer.getvalue())
    response.headers['Content-Type']='application/pdf'
    response.headers['Content-Disposition']=f"attachment; filename=OXYZON GYM_Member_{user['id']}.pdf"
    return response

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
