import eventlet
import os
import psycopg2
import logging
import traceback
from flask import (
    Flask, render_template, render_template_string,
    request, redirect, url_for, session, send_from_directory
)
from flask_socketio import SocketIO, send, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import smtplib
import random
import string
from datetime import datetime, timedelta
from email.mime.text import MIMEText

# ---------------- Config -----------------
DATABASE_URL = os.environ.get("DATABASE_URL")
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "uploads")
EMAIL_ADDRESS = os.environ.get("EMAIL_USER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASS")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change_this_secret")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
socketio = SocketIO(app, cors_allowed_origins="*")

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger("werkzeug")
log.setLevel(logging.DEBUG)

# ---------------- Error Handler -----------------
@app.errorhandler(Exception)
def handle_exception(e):
    print("🔥 ERROR TRACEBACK START 🔥")
    traceback.print_exc()
    print("🔥 ERROR TRACEBACK END 🔥")
    return "Internal Server Error - Check Logs", 500

# ---------------- Database Setup -----------------
def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set in environment")
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            fullname TEXT,
            dob DATE,
            profile_pic TEXT,
            email TEXT UNIQUE,
            reset_otp TEXT,
            otp_expiry TIMESTAMP,
            verified BOOLEAN DEFAULT FALSE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS friends (
            id SERIAL PRIMARY KEY,
            user1 TEXT NOT NULL,
            user2 TEXT NOT NULL,
            status TEXT DEFAULT 'accepted',
            UNIQUE(user1, user2)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id SERIAL PRIMARY KEY,
            sender TEXT NOT NULL,
            receiver TEXT NOT NULL,
            message TEXT,
            file TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            file TEXT,
            caption TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    c.close()
    conn.close()

# ---------------- OTP Email -----------------
def send_otp(email, otp):
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        print(f"⚠️ Skipping email send. OTP for {email} is {otp}")
        return
    msg = MIMEText(f"Your OTP is {otp}. It expires in 5 minutes.")
    msg["Subject"] = "App OTP Verification"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = email
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, [email], msg.as_string())

# ---------------- Register -----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username").strip()
        email = request.form.get("email").strip()
        dob = request.form.get("dob")
        password = request.form.get("password")

        conn = get_db_connection()
        c = conn.cursor()
        try:
            otp = "".join(random.choices(string.digits, k=6))
            expiry = datetime.utcnow() + timedelta(minutes=5)
            c.execute("""INSERT INTO users (username,email,dob,password_hash,reset_otp,otp_expiry)
                         VALUES (%s,%s,%s,%s,%s,%s)""",
                      (username, email, dob, generate_password_hash(password), otp, expiry))
            conn.commit()
            send_otp(email, otp)
        except Exception as e:
            conn.rollback()
            return f"❌ Registration failed: {e}", 400
        finally:
            c.close()
            conn.close()
        return redirect(url_for("verify", email=email))

    return render_template_string("""
    <h2>Register</h2>
    <form method=post>
      <input name=username placeholder="Username" required><br>
      <input name=email type=email placeholder="Email" required><br>
      <input name=dob type=date required><br>
      <input name=password type=password placeholder="Password" required><br>
      <button>Register</button>
    </form>
    """)

# ---------------- Verify OTP -----------------
@app.route("/verify", methods=["GET","POST"])
def verify():
    email = request.args.get("email") or request.form.get("email")
    if request.method == "POST":
        otp = request.form.get("otp")
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT reset_otp, otp_expiry FROM users WHERE email=%s", (email,))
        row = c.fetchone()
        if not row:
            return "❌ Invalid email", 400
        db_otp, expiry = row
        if otp != db_otp or datetime.utcnow() > expiry:
            return "❌ Invalid or expired OTP", 400
        c.execute("UPDATE users SET verified=TRUE, reset_otp=NULL, otp_expiry=NULL WHERE email=%s", (email,))
        conn.commit()
        c.close(); conn.close()
        return redirect(url_for("login"))
    return render_template_string("""
    <h2>Verify OTP</h2>
    <form method=post>
      <input type=hidden name=email value='{{email}}'>
      <input name=otp placeholder="Enter OTP"><br>
      <button>Verify</button>
    </form>
    """, email=email)

# ---------------- Login -----------------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT password_hash, verified FROM users WHERE username=%s", (username,))
        row = c.fetchone()
        c.close(); conn.close()
        if row and check_password_hash(row[0], password) and row[1]:
            session["user"] = username
            return redirect(url_for("dashboard"))
        return "❌ Invalid credentials or not verified"
    return render_template_string("""
    <h2>Login</h2>
    <form method=post>
      <input name=username placeholder=Username><br>
      <input name=password type=password placeholder=Password><br>
      <button>Login</button>
    </form>
    """)

# ---------------- Friend Requests -----------------
@app.route("/users")
def all_users():
    if "user" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    c = conn.cursor()
    # All users except self
    c.execute("SELECT username FROM users WHERE username!=%s AND verified=TRUE", (session["user"],))
    users = c.fetchall()
    # Incoming requests
    c.execute("SELECT user1 FROM friends WHERE user2=%s AND status='pending'", (session["user"],))
    requests = c.fetchall()
    c.close(); conn.close()
    return render_template("users.html", users=users, requests=requests)

@app.route("/send_request/<username>")
def send_request(username):
    if "user" not in session:
        return redirect(url_for("login"))
    sender = session["user"]
    receiver = username
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # Avoid duplicates
        c.execute("SELECT * FROM friends WHERE user1=%s AND user2=%s", (sender, receiver))
        if not c.fetchone():
            c.execute("INSERT INTO friends (user1, user2, status) VALUES (%s,%s,'pending')", (sender, receiver))
            conn.commit()
    except Exception as e:
        conn.rollback()
    finally:
        c.close(); conn.close()
    return redirect(url_for("all_users"))

@app.route("/respond_request/<username>/<action>")
def respond_request(username, action):
    if "user" not in session:
        return redirect(url_for("login"))
    receiver = session["user"]
    sender = username
    conn = get_db_connection()
    c = conn.cursor()
    if action == "accept":
        c.execute("UPDATE friends SET status='accepted' WHERE user1=%s AND user2=%s", (sender, receiver))
    elif action == "reject":
        c.execute("DELETE FROM friends WHERE user1=%s AND user2=%s", (sender, receiver))
    conn.commit(); c.close(); conn.close()
    return redirect(url_for("all_users"))

# ---------------- Dashboard -----------------
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    c = conn.cursor()
    # Only accepted friends
    c.execute("""
        SELECT user1 FROM friends WHERE user2=%s AND status='accepted'
        UNION
        SELECT user2 FROM friends WHERE user1=%s AND status='accepted'
    """, (session["user"], session["user"]))
    friends = c.fetchall()
    c.close(); conn.close()
    return render_template("dashboard.html", user=session["user"], friends=friends)

# ---------------- Profile -----------------
@app.route("/profile/<username>")
def profile(username):
    if "user" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT username, profile_pic, dob FROM users WHERE username=%s", (username,))
    user = c.fetchone()
    c.close(); conn.close()
    if not user:
        return "User not found", 404
    username, profile_pic, dob = user
    dob_str = dob.strftime("%d %B") if dob else "Not set"
    return render_template("profile.html", username=username, profile_pic=profile_pic, dob=dob_str)

# ---------------- Chat -----------------
@app.route("/chat/<friend>")
def chat(friend):
    if "user" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT sender,receiver,message,file,timestamp FROM chats WHERE (sender=%s AND receiver=%s) OR (sender=%s AND receiver=%s) ORDER BY timestamp",
              (session["user"], friend, friend, session["user"]))
    msgs = c.fetchall()
    c.close(); conn.close()
    return render_template("chat.html", user=session["user"], friend=friend, messages=msgs)

@socketio.on("send_message")
def handle_message(data):
    sender = session.get("user")
    receiver = data.get("receiver")
    message = data.get("message")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO chats (sender,receiver,message) VALUES (%s,%s,%s)", (sender, receiver, message))
    conn.commit(); c.close(); conn.close()
    emit("new_message", {"sender": sender, "message": message}, room=receiver)

# ---------------- Feed (Instagram style) -----------------
@app.route("/feed", methods=["GET","POST"])
def feed():
    if "user" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        file = request.files.get("file")
        caption = request.form.get("caption")
        if file:
            filename = secure_filename(file.filename)
            path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            file.save(path)
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM users WHERE username=%s", (session["user"],))
            user_id = c.fetchone()[0]
            c.execute("INSERT INTO posts (user_id,file,caption) VALUES (%s,%s,%s)", (user_id, filename, caption))
            conn.commit(); c.close(); conn.close()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT u.username,u.profile_pic,p.file,p.caption,p.timestamp FROM posts p JOIN users u ON p.user_id=u.id ORDER BY p.timestamp DESC")
    posts = c.fetchall()
    c.close(); conn.close()
    return render_template("feed.html", posts=posts)

# ---------------- Logout -----------------
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

# ---------------- Main -----------------
init_db()
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
