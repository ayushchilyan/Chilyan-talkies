import os, sqlite3, uuid, datetime
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

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

# -------------- DB Helpers ------------------
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
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            note TEXT DEFAULT 'Happy Birthday 🎂',
            slug TEXT UNIQUE NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,     -- photo / video / audio
            filename TEXT NOT NULL, -- stored file name
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

init_db()

# -------------- Utilities -------------------
def user_dirs(username):
    root = os.path.join(UPLOAD_ROOT, username)
    photos = os.path.join(root, "photos")
    videos = os.path.join(root, "videos")
    audios = os.path.join(root, "audios")
    for d in (root, photos, videos, audios):
        os.makedirs(d, exist_ok=True)
    return {"root": root, "photos": photos, "videos": videos, "audios": audios}

def get_user(username):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row

def get_user_by_slug(slug):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    return row

def create_user(username, password, note):
    slug = f"{username}-{uuid.uuid4().hex[:6]}"
    pwd = generate_password_hash(password)
    conn = get_db()
    conn.execute("INSERT INTO users (username, password_hash, note, slug) VALUES (?,?,?,?)",
                 (username, pwd, note or "Happy Birthday 🎂", slug))
    conn.commit()
    conn.close()
    user_dirs(username)
    return slug

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

# -------------- Routes ----------------------
@app.route("/")
def root():
    if session.get("uid"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        note = (request.form.get("note") or "").strip()

        if not username or not password:
            flash("Please fill all fields.", "error")
            return render_template("register.html")

        if get_user(username):
            flash("Username already exists.", "error")
            return render_template("register.html")

        slug = create_user(username, password, note)
        flash("Registered successfully. Please login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        user = get_user(username)
        if user and check_password_hash(user["password_hash"], password):
            session["uid"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))
        flash("Wrong username or password.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard", methods=["GET","POST"])
def dashboard():
    if not session.get("uid"):
        return redirect(url_for("login"))
    user = get_user(session["username"])

    # Update note
    if request.method == "POST" and "note" in request.form:
        new_note = (request.form.get("note") or "").strip()
        conn = get_db()
        conn.execute("UPDATE users SET note = ? WHERE id = ?", (new_note or user["note"], user["id"]))
        conn.commit()
        conn.close()
        flash("Message updated!", "success")
        return redirect(url_for("dashboard"))

    # Upload
    if request.method == "POST" and "file" in request.files:
        f = request.files["file"]
        if f and allowed_file(f.filename):
            _, err = save_media(user, f)
            flash("File uploaded!" if not err else err, "success" if not err else "error")
        else:
            flash("Please choose a valid file.", "error")
        return redirect(url_for("dashboard"))

    # Listing
    conn = get_db()
    photos = conn.execute("SELECT filename FROM media WHERE user_id=? AND kind='photo' ORDER BY id DESC", (user["id"],)).fetchall()
    videos = conn.execute("SELECT filename FROM media WHERE user_id=? AND kind='video' ORDER BY id DESC", (user["id"],)).fetchall()
    audios = conn.execute("SELECT filename FROM media WHERE user_id=? AND kind='audio' ORDER BY id DESC", (user["id"],)).fetchall()
    user = get_user(session["username"])  # refresh note + slug
    conn.close()

    share_url = url_for("wish_public", slug=user["slug"], _external=True)
    return render_template("dashboard.html",
                           photos=photos, videos=videos, audios=audios,
                           share_url=share_url, note=user["note"], username=user["username"])

@app.route("/w/<slug>")
def wish_public(slug):
    user = get_user_by_slug(slug)
    if not user:
        return render_template("wish.html", not_found=True), 404

    dirs = user_dirs(user["username"])
    photo_urls = [url_for("serve_upload", username=user["username"], media="photos", filename=f)
                  for f in sorted(os.listdir(dirs["photos"])) if not f.startswith(".")]
    video_urls = [url_for("serve_upload", username=user["username"], media="videos", filename=f)
                  for f in sorted(os.listdir(dirs["videos"])) if not f.startswith(".")]
    audio_urls = [url_for("serve_upload", username=user["username"], media="audios", filename=f)
                  for f in sorted(os.listdir(dirs["audios"])) if not f.startswith(".")]

    return render_template("wish.html",
                           not_found=False,
                           note=user["note"],
                           photos=photo_urls, videos=video_urls, audios=audio_urls)

# Serve uploaded files
@app.route("/uploads/<username>/<media>/<path:filename>")
def serve_upload(username, media, filename):
    dirs = user_dirs(username)
    base = {"photos": dirs["photos"], "videos": dirs["videos"], "audios": dirs["audios"]}.get(media)
    if not base:
        return "Not found", 404
    return send_from_directory(base, filename, as_attachment=False)

if __name__ == "__main__":
    app.run(debug=True)
