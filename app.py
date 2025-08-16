import os
import uuid
import datetime
import sqlite3
from flask import Flask, redirect, url_for, render_template, request, session, flash, send_from_directory
from authlib.integrations.flask_client import OAuth
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

client_id = os.getenv("GOOGLE_CLIENT_ID")
client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

flow = Flow.from_client_config(
    {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            ...
        }
    },
    scopes=["..."]
)

# ---------------- App Config ----------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "app.db")
UPLOAD_ROOT = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_ROOT, exist_ok=True)

ALLOWED_PHOTO = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_VIDEO = {"mp4", "mov", "m4v", "webm"}
ALLOWED_AUDIO = {"mp3", "wav", "m4a", "aac"}
ALLOWED_ALL = ALLOWED_PHOTO | ALLOWED_VIDEO | ALLOWED_AUDIO

app = Flask(__name__)
app.config["SECRET_KEY"] = "CHANGE_ME_SUPER_SECRET"
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64 MB


# ---------------- DB Helpers ----------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            name TEXT,
            email TEXT UNIQUE,
            password_hash TEXT,
            dob TEXT,
            note TEXT DEFAULT 'Happy Birthday 🎂',
            slug TEXT UNIQUE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            filename TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------------- Utilities ----------------
def user_dirs(username):
    root = os.path.join(UPLOAD_ROOT, username)
    photos = os.path.join(root, "photos")
    videos = os.path.join(root, "videos")
    audios = os.path.join(root, "audios")
    for d in (root, photos, videos, audios):
        os.makedirs(d, exist_ok=True)
    return {"root": root, "photos": photos, "videos": videos, "audios": audios}

def get_user(username=None, email=None):
    conn = get_db()
    if username:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    elif email:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    else:
        row = None
    conn.close()
    return row

def get_user_by_slug(slug):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    return row

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_ALL

def classify_ext(ext):
    ext = ext.lower()
    if ext in ALLOWED_PHOTO: return "photo"
    if ext in ALLOWED_VIDEO: return "video"
    if ext in ALLOWED_AUDIO: return "audio"
    return None

def save_media(user, file_storage):
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit(".", 1)[1].lower()
    kind = classify_ext(ext)
    if not kind: return None, "Invalid file type."
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    final_name = f"{stamp}_{uuid.uuid4().hex[:6]}.{ext}"
    dirs = user_dirs(user["username"])
    dest_dir = {"photo": dirs["photos"], "video": dirs["videos"], "audio": dirs["audios"]}[kind]
    file_storage.save(os.path.join(dest_dir, final_name))
    conn = get_db()
    conn.execute(
        "INSERT INTO media (user_id, kind, filename, created_at) VALUES (?,?,?,?)",
        (user["id"], kind, final_name, datetime.datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()
    return kind, None

# ---------------- Routes ----------------
@app.route("/")
def home():
    if "user" in session:
        return f"Welcome {session['user']['name']}! Your DOB: {session['user']['dob']}"
    return render_template("home.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        dob = request.form["dob"]
        conn = get_db()
        try:
            conn.execute("INSERT INTO users (name,email,dob,slug) VALUES (?,?,?,?)",
                         (name, email, dob, f"{name}-{uuid.uuid4().hex[:6]}"))
            conn.commit()
        except sqlite3.IntegrityError:
            flash("Email already registered!", "error")
            return redirect(url_for("register"))
        conn.close()
        return redirect(url_for("login"))
    return render_template("register.html")

# ---------------- OAuth Setup ----------------
oauth = OAuth(app)
oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    access_token_url="https://accounts.google.com/o/oauth2/token",
    authorize_url="https://accounts.google.com/o/oauth2/auth",
    api_base_url="https://www.googleapis.com/oauth2/v1/",
    client_kwargs={"scope": "openid email profile"},
)

# ---------------- Routes ----------------
@app.route("/login")
def login():
    redirect_uri = url_for("authorize", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)   # <- fix here

@app.route("/authorize")
def authorize():
    token = oauth.google.authorize_access_token()         # <- fix here
    user_info = oauth.google.parse_id_token(token)        # <- fix here
    email = user_info["email"]
    user = get_user(email=email)
    if user:
        session["user"] = {
            "name": user["name"],
            "email": user["email"],
            "dob": user["dob"],
            "username": user["username"]
        }
        return redirect(url_for("home"))
    else:
        session["temp_email"] = email
        return redirect(url_for("complete_registration"))

@app.route("/complete_registration", methods=["GET", "POST"])
def complete_registration():
    if "temp_email" not in session:
        return redirect(url_for("home"))
    if request.method == "POST":
        name = request.form["name"]
        dob = request.form["dob"]
        email = session["temp_email"]
        slug = f"{name}-{uuid.uuid4().hex[:6]}"
        conn = get_db()
        conn.execute("INSERT INTO users (name,email,dob,slug) VALUES (?,?,?,?)", (name,email,dob,slug))
        conn.commit()
        conn.close()
        session["user"] = {"name": name, "email": email, "dob": dob, "username": name}
        session.pop("temp_email", None)
        return redirect(url_for("home"))
    return render_template("complete_registration.html", email=session["temp_email"])

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard", methods=["GET","POST"])
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    user = get_user(username=session["user"]["username"])
    # ... Dashboard logic (upload files, notes, list media) ...
    return render_template("dashboard.html")

@app.route("/w/<slug>")
def wish_public(slug):
    user = get_user_by_slug(slug)
    if not user:
        return render_template("wish.html", not_found=True), 404
    dirs = user_dirs(user["username"])
    photo_urls = [url_for("serve_upload", username=user["username"], media="photos", filename=f)
                  for f in sorted(os.listdir(dirs["photos"])) if not f.startswith(".")]
    return render_template("wish.html", not_found=False, note=user["note"], photos=photo_urls)

@app.route("/uploads/<username>/<media>/<path:filename>")
def serve_upload(username, media, filename):
    dirs = user_dirs(username)
    base = {"photos": dirs["photos"], "videos": dirs["videos"], "audios": dirs["audios"]}.get(media)
    if not base:
        return "Not found", 404
    return send_from_directory(base, filename, as_attachment=False)

if __name__ == "__main__":
    app.run(debug=True)
