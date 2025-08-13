from flask import Flask, render_template, request, redirect, url_for, session
import json, os

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = "super_secret_key"

USERS_FILE = "users.json"

# Load users from file
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r") as f:
        return json.load(f)

# Save users to file
def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password").strip()
        if not username or not password:
            return render_template("register.html", error="Please fill all fields.")

        users = load_users()
        if username in users:
            return render_template("register.html", error="User already exists!")

        users[username] = password
        save_users(users)
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password").strip()

        users = load_users()
        if username in users and users[username] == password:
            session["logged_in"] = True
            session["username"] = username
            return redirect(url_for("gift"))
        else:
            return render_template("login.html", error="Wrong username or password.")
    return render_template("login.html")

@app.route("/gift")
def gift():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    photos = [
        
        {"src": "/static/photos/first01.PNG", "caption": "Bade logo ke sath hamara phela photo session 😄"},
        {"src": "/static/photos/4.jpg", "caption": "Remember this maggie party mam?"},
        {"src": "/static/photos/1.jpg", "caption": "Happy Birthday Mam"},
        {"src": "/static/photos/5.jpg", "caption": "Our selfie 😄"},
        {"src": "/static/photos/3.jpg", "caption": "12th Ka Last Day😢"},
        
    ]
    videos = [
        {"src": "/static/videos/01.mp4", "title": "A Funny Video", "poster": "/static/photos/photo1.jpg"}
    ]
    audios = [
        {"src": "/static/audios/01.mp3", "title": "Happy Birthday Song✨"}
    ]
    downloads = [
        {"href": "/static/downloads/letter.pdf", "label": "Open your letter (PDF)"}
    ]
    note = " Happy Birthday to an extraordinary teacher and an incredible person! On your Sepcial day, I want to express my heartfelt gratitude for all that you do. Your dedication, guidance, and unwavering support have made a profound impact on my life. I'm so thankful for the lessons you've taught me. Bahut yaad aati hai Mam Kaise Classes Bunk krke aapse milne aa jate the,  Janamdin ki bahut bahut Badhai Mam 🎂💫"

    return render_template("gift.html",
                           username=session.get("username"),
                           photos=photos, videos=videos,
                           audios=audios, downloads=downloads, note=note)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)
