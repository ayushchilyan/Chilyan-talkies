from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from flask_socketio import SocketIO, send
import os
import sqlite3


app = Flask(__name__)
app.secret_key = "secret"
socketio = SocketIO(app, cors_allowed_origins="*")
UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ---------------- Database Setup -----------------
def init_db():
    # Agar purana db hai to hata de (sirf development me)
    if os.path.exists("users.db"):
        os.remove("users.db")

    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fullname TEXT NOT NULL,
                    dob TEXT NOT NULL,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    mobile TEXT NOT NULL,
                    password TEXT NOT NULL,
                    note TEXT,
                    file TEXT
                )""")
    
    # Friend requests table
    c.execute("""CREATE TABLE friend_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT NOT NULL,
                    receiver TEXT NOT NULL,
                    status TEXT DEFAULT 'pending'
                )""")

    conn.commit()
    conn.close()

# ---------------- Serve Uploaded Media -----------------
@app.route("/uploads/<username>/<media>/<filename>")
def serve_upload(username, media, filename):
    folder = os.path.join(app.config["UPLOAD_FOLDER"], username, media)
    return send_from_directory(folder, filename)

# ---------------- Home -----------------
@app.route("/")
def home():
    return redirect(url_for("login"))

# ---------------- Register -----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        fullname = request.form["fullname"]
        dob = request.form["dob"]
        username = request.form["username"]
        email = request.form["email"]
        mobile = request.form["mobile"]
        password = request.form["password"]

        if len(password) < 6:
            return "❌ Password must be at least 6 characters long!"

        conn = sqlite3.connect("users.db")
        c = conn.cursor()
        try:
            c.execute("""INSERT INTO users (fullname, dob, username, email, mobile, password) 
                         VALUES (?, ?, ?, ?, ?, ?)""", 
                         (fullname, dob, username, email, mobile, password))
            conn.commit()
        except sqlite3.IntegrityError:
            return "⚠️ Username or Email already exists!"
        finally:
            conn.close()

        return redirect(url_for("login"))
    
    return render_template("register.html")

# ---------------- Login -----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("users.db")
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
        user = c.fetchone()
        conn.close()

        if user:
            session["user"] = username
            return redirect(url_for("dashboard"))
        else:
            return "❌ Invalid Credentials! Try again."
    
    return render_template("index.html")

# ---------------- Dashboard -----------------
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    username = session["user"]
    user_dir = os.path.join(app.config["UPLOAD_FOLDER"], username)
    photos_dir = os.path.join(user_dir, "photos")
    videos_dir = os.path.join(user_dir, "videos")
    audios_dir = os.path.join(user_dir, "audios")

    for d in [photos_dir, videos_dir, audios_dir]:
        os.makedirs(d, exist_ok=True)

    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT note FROM users WHERE username=?", (username,))
    row = c.fetchone()
    note = row[0] if row else ""

    share_url = request.host_url + "wish/" + username

    if request.method == "POST":
        # Note save
        if "note" in request.form:
            note = request.form["note"]
            c.execute("UPDATE users SET note=? WHERE username=?", (note, username))
            conn.commit()

        # Photo upload
        if "photo_file" in request.files:
            f = request.files["photo_file"]
            if f.filename:
                f.save(os.path.join(photos_dir, f.filename))

        # Video upload
        if "video_file" in request.files:
            f = request.files["video_file"]
            if f.filename:
                f.save(os.path.join(videos_dir, f.filename))

        # Audio upload
        if "audio_file" in request.files:
            f = request.files["audio_file"]
            if f.filename:
                f.save(os.path.join(audios_dir, f.filename))

    conn.close()

    photos = [{"filename": f} for f in os.listdir(photos_dir)]
    videos = [{"filename": f} for f in os.listdir(videos_dir)]
    audios = [{"filename": f} for f in os.listdir(audios_dir)]

    return render_template(
    "dashboard.html",
    username=username,
    note=note,
    share_url=share_url,
    photos=photos,
    videos=videos,
    audios=audios
)

#friend list dikhana


@app.route("/users")
def users_list():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT username, fullname FROM users WHERE username != ?", (session["user"],))
    users = c.fetchall()
    conn.close()

    return render_template("users.html", users=users)


# request dikhana

@app.route("/send_request/<receiver>")
def send_request(receiver):
    if "user" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("INSERT INTO friend_requests (sender, receiver, status) VALUES (?, ?, ?)",
              (session["user"], receiver, "pending"))
    conn.commit()
    conn.close()

    return redirect(url_for("users_list"))


#request pending

@app.route("/requests")
def friend_requests():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT id, sender FROM friend_requests WHERE receiver=? AND status='pending'", (session["user"],))
    requests = c.fetchall()
    conn.close()

    return render_template("requests.html", requests=requests)

#accept/reject


@app.route("/accept/<int:req_id>")
def accept_request(req_id):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("UPDATE friend_requests SET status='accepted' WHERE id=?", (req_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("friend_requests"))

@app.route("/reject/<int:req_id>")
def reject_request(req_id):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("UPDATE friend_requests SET status='rejected' WHERE id=?", (req_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("friend_requests"))


# Friends list (accepted only)

@app.route("/friends")
def friends_list():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("""SELECT sender, receiver FROM friend_requests 
                 WHERE (sender=? OR receiver=?) AND status='accepted'""",
              (session["user"], session["user"]))
    data = c.fetchall()
    conn.close()

    # Current user ka naam hata kar dusra dikhana
    friends = [u[0] if u[0] != session["user"] else u[1] for u in data]

    return render_template("friends.html", friends=friends)



# ---------------- Wish Page -----------------@app.route("/wish/<username>")
def wish(username):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT fullname, note, file FROM users WHERE username=?", (username,))
    data = c.fetchone()
    conn.close()

    if not data:
        return "User not found!"

    fullname, note, file = data
    file_url = None
    if file:
        file_url = url_for("static", filename="uploads/" + file)

    # user ke uploads dikhane ke liye
    user_dir = os.path.join(app.config["UPLOAD_FOLDER"], username)
    photos = [{"filename": f} for f in os.listdir(os.path.join(user_dir,"photos"))] if os.path.exists(os.path.join(user_dir,"photos")) else []
    videos = [{"filename": f} for f in os.listdir(os.path.join(user_dir,"videos"))] if os.path.exists(os.path.join(user_dir,"videos")) else []
    audios = [{"filename": f} for f in os.listdir(os.path.join(user_dir,"audios"))] if os.path.exists(os.path.join(user_dir,"audios")) else []

    return render_template("wish.html",
                           user=fullname,
                           note=note,
                           file_url=file_url,
                           username=username,
                           photos=photos,
                           videos=videos,
                           audios=audios)


# ---------------- Chat -----------------
@app.route("/chat")
def chat():
    if "user" in session:
        return render_template("chat.html", user=session["user"])
    return redirect(url_for("login"))

# --- SocketIO events ---
@socketio.on("message")
def handle_message(msg):
    print("Message: " + msg)
    send(msg, broadcast=True)

# ---------------- Logout -----------------
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

if __name__ == "__main__":
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    init_db()  # har run pe db check/create hoga

    socketio.run(app, host="0.0.0.0", port=5000)
