import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)  # production: set to a fixed secret

DB = "todo.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        created_at TEXT,
        due_date TEXT,
        completed INTEGER DEFAULT 0,
        color_tag TEXT DEFAULT '#00FFA3',
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """)
    conn.commit()
    conn.close()

init_db()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/")
@login_required
def index():
    user_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE user_id=? ORDER BY completed, due_date NULLS LAST, created_at DESC", (user_id,))
    tasks = cur.fetchall()
    conn.close()
    return render_template("index.html", tasks=tasks, username=session.get("username"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        if not username or not password:
            flash("Please provide username and password.", "danger")
            return redirect(url_for("register"))
        hashed = generate_password_hash(password)
        conn = get_db()
        try:
            conn.execute("INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)",
                         (username, hashed, datetime.utcnow().isoformat()))
            conn.commit()
            conn.close()
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already taken. Choose another one.", "danger")
            conn.close()
            return redirect(url_for("register"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cur.fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for("index"))
        flash("Invalid username or password.", "danger")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))

@app.route("/add", methods=["POST"])
@login_required
def add_task():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    due_date = request.form.get("due_date") or None
    color_tag = request.form.get("color_tag") or "#00FFA3"
    if not title:
        flash("Task title cannot be empty.", "danger")
        return redirect(url_for("index"))
    conn = get_db()
    conn.execute(
        "INSERT INTO tasks (user_id, title, description, created_at, due_date, color_tag) VALUES (?, ?, ?, ?, ?, ?)",
        (session["user_id"], title, description, datetime.utcnow().isoformat(), due_date, color_tag)
    )
    conn.commit()
    conn.close()
    flash("Task added!", "success")
    return redirect(url_for("index"))

@app.route("/delete/<int:task_id>", methods=["POST"])
@login_required
def delete_task(task_id):
    conn = get_db()
    conn.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "msg": "Deleted"})

@app.route("/toggle/<int:task_id>", methods=["POST"])
@login_required
def toggle_task(task_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT completed FROM tasks WHERE id=? AND user_id=?", (task_id, session["user_id"]))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"status": "error", "msg": "Not found"}), 404
    new = 0 if row["completed"] else 1
    cur.execute("UPDATE tasks SET completed=? WHERE id=? AND user_id=?", (new, task_id, session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "completed": new})

@app.route("/edit/<int:task_id>", methods=["GET", "POST"])
@login_required
def edit(task_id):
    conn = get_db()
    cur = conn.cursor()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        due_date = request.form.get("due_date") or None
        color_tag = request.form.get("color_tag") or "#00FFA3"
        if not title:
            flash("Title can't be empty.", "danger")
            return redirect(url_for("edit", task_id=task_id))
        cur.execute("""UPDATE tasks SET title=?, description=?, due_date=?, color_tag=? 
                       WHERE id=? AND user_id=?""",
                    (title, description, due_date, color_tag, task_id, session["user_id"]))
        conn.commit()
        conn.close()
        flash("Task updated.", "success")
        return redirect(url_for("index"))

    cur.execute("SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, session["user_id"]))
    task = cur.fetchone()
    conn.close()
    if not task:
        flash("Task not found or access denied.", "danger")
        return redirect(url_for("index"))
    return render_template("edit.html", task=task)

@app.route("/api/tasks")
@login_required
def api_tasks():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE user_id=? ORDER BY completed, due_date NULLS LAST, created_at DESC", (session["user_id"],))
    tasks = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify(tasks)

if __name__ == "__main__":
    app.run(debug=True)
