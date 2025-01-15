import hashlib
import json
import re
import os
import math
import uuid
import collections
from collections import defaultdict
import random
import time

from operator import itemgetter
from datetime import datetime
from urllib.parse import urlparse
import urllib.parse

import requests
import nh3
import boto3

from flask import *

from flask_mysqldb import MySQL
from flask_htmlmin import HTMLMIN

from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect

from cryptography.hazmat.primitives import serialization as crypto_serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend as crypto_default_backend

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import sqlalchemy

from moviepy import VideoFileClip

import vidzyconfig

CLEANR = re.compile('<.*?>')
def cleanhtml(raw_html):
    cleantext = re.sub(CLEANR, '', raw_html)
    return cleantext

key = rsa.generate_private_key(
    backend=crypto_default_backend(),
    public_exponent=65537,
    key_size=2048
)

private_key = key.private_bytes(
    crypto_serialization.Encoding.PEM,
    crypto_serialization.PrivateFormat.PKCS8,
    crypto_serialization.NoEncryption())

public_key = key.public_key().public_bytes(
    crypto_serialization.Encoding.PEM,
    crypto_serialization.PublicFormat.SubjectPublicKeyInfo
)


VIDZY_VERSION = "v0.2.0"

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'mp4', 'webm', 'mkv'}

mysql = MySQL()
app = Flask(__name__, static_url_path='')
csrf = CSRFProtect(app)

app.jinja_env.globals.update(VIDZY_VERSION=VIDZY_VERSION)

app.config.from_pyfile('settings.py', silent=False)
if app.config['SENTRY_ENABLED']:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration

    sentry_sdk.init(
        dsn=app.config['SENTRY_DSN'],
        integrations=[FlaskIntegration()]
    )
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['WTF_CSRF_CHECK_DEFAULT'] = False
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://{}:{}@{}:{}/{}'.format(app.config["MYSQL_USER"], app.config["MYSQL_PASSWORD"], app.config["MYSQL_HOST"], app.config["MYSQL_PORT"], app.config["MYSQL_DB"])
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

if app.config['MINIFY_HTML']:
    htmlmin = HTMLMIN(app, remove_comments=True)

mysql.init_app(app)

s3_enabled = app.config['S3_ENABLED']
print("S3 enabled:", s3_enabled)

Base = declarative_base()

db = SQLAlchemy(app)
db.init_app(app)

engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'], isolation_level="AUTOCOMMIT", pool_pre_ping=True)

SQLAlchemy_Session = sessionmaker(bind=engine)
SQLAlchemy_session = SQLAlchemy_Session()

@sqlalchemy.event.listens_for(engine, "handle_error")
def handle_error(ctx):
    if isinstance(ctx.original_exception, KeyboardInterrupt):
        print("keyboard interrupt intercepted, keeping connection opened")
        ctx.is_disconnect = False

#class Shorts(Base):
#    __tablename__ = 'shorts'
#
#    id = db.Column(db.Integer, primary_key=True)
#    title = db.Column(db.String(65))
#    url = db.Column(db.String(60))
#    user_id = db.Column(db.Integer, primary_key=False)
#    date_uploaded = db.Column(db.Date, default=datetime.now().strftime('%Y-%m-%d'), nullable=True)

class Comment(Base):
    __tablename__ = 'vidcomments'
    _N = 6

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    text = db.Column(db.String(140))
    author = db.Column(db.String(32))
    timestamp = db.Column(db.DateTime(), default=datetime.utcnow, index=True)
    short_id = db.Column(db.Integer, primary_key=False)
    path = db.Column(db.Text(400), index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('vidcomments.id'))
    replies = db.relationship(
        'Comment', backref=db.backref('parent', remote_side=[id]),
        lazy='dynamic')

    def save(self):
        SQLAlchemy_session.add(self)
        SQLAlchemy_session.commit()
        prefix = self.parent.path + '.' if self.parent else ''
        self.path = prefix + '{:0{}d}'.format(self.id, self._N)
        SQLAlchemy_session.commit()

    def level(self):
        if self.path == None:
            return 1
        return len(self.path) // self._N - 1

with app.app_context():
    Base.metadata.create_all(engine)

# For now, the random will make the share number a little better
@app.template_filter('random_share_num')
def random_share_num(lol):
    return random.randint(35, 171)

@app.template_filter('get_gravatar')
def get_gravatar(email):
    return "https://www.gravatar.com/avatar/" + hashlib.md5(email.encode()).hexdigest() + "?d=mp"

@app.template_filter('get_comments')
def get_comments(vid):
    mycursor = mysql.connection.cursor()

    mycursor.execute("SELECT * FROM `vidcomments` WHERE short_id = %s;", (vid,))
    myresult = mycursor.fetchall()

    return myresult

@app.template_filter('get_comment_count')
def get_comment_count(vid):
    cursor = mysql.connection.cursor()

    cursor.execute("SELECT count(*) comment_count FROM `vidcomments` WHERE short_id = %s;", (vid,))
    comment_count = int(cursor.fetchall()[0]["comment_count"])

    return comment_count

@app.template_filter('get_user_info')
def get_user_info(userid):
    mycursor = mysql.connection.cursor()

    mycursor.execute("SELECT * FROM `users` WHERE id = %s;", (userid,))
    myresult = mycursor.fetchall()[0]

    return myresult

@app.template_filter('get_username')
def get_username(userid):
    return get_user_info(userid)["username"]

def delete_non_existent_files_from_shorts():
    entries_deleted = 0

    cursor = mysql.connection.cursor()
    
    try:
        cursor.execute("SELECT `id`, `url` FROM `shorts`")
        rows = cursor.fetchall()
        
        for row in rows:
            short_id = row["id"]
            file_path = row["url"]
            
            full_file_path = os.path.join(os.path.join(app.config['UPLOAD_FOLDER'], file_path))
            
            if not os.path.exists(full_file_path) and not file_path.startswith("http://") and not file_path.startswith("https://"):
                print(f"File {full_file_path} does not exist. Deleting entry from database.")
                
                cursor.execute("DELETE FROM `shorts` WHERE `id` = %s", (short_id,))
                mysql.connection.commit()

                entries_deleted += 1
        
        print("Cleanup complete.")
    
    except Exception as err:
        print(f"Error: {err}")
        mysql.connection.rollback()
    
    finally:
        cursor.close()
    
    return entries_deleted

@app.route("/camera")
def camera_route():
    return app.send_static_file('demos/threejs/glassesVTO/index.html')

@app.route("/comments/<shortid>")
def comments_route(shortid):
    comments = SQLAlchemy_session.query(Comment).filter(Comment.short_id == shortid).order_by(Comment.path)

    try:
        return render_template("comments.html", comments=comments)
    except sqlalchemy.exc.PendingRollbackError:
        SQLAlchemy_session.rollback()
        return render_template("comments.html", comments=comments)

@app.route("/like_post")
def like_post_page():
    if "user" not in session:
        return "NotLoggedIn"

    mycursor = mysql.connection.cursor()

    mycursor.execute("SELECT * FROM likes WHERE short_id = %s AND user_id = %s;", (str(request.args.get("id")), str(session["user"]["id"])))

    myresult = mycursor.fetchall()

    for _ in myresult:
        return "Already Liked"

    mycursor = mysql.connection.cursor()

    sql = "INSERT INTO `likes` (`short_id`, `user_id`) VALUES (%s, %s)"
    val = (request.args.get("id"), session["user"]["id"])
    mycursor.execute(sql, val)

    mysql.connection.commit()

    return "Success"

@app.route("/send_comment")
def send_comment_page():
    if "user" not in session:
        return "NotLoggedIn"

    parent_comment = request.args.get("parent", default=None)
    if parent_comment is not None:
        parent_comment = SQLAlchemy_session.query(Comment).get(int(parent_comment))

    shortid = request.args.get("shortid")

    cursor = mysql.connection.cursor()
    cursor.execute("SELECT count(*) comment_count FROM `comments` WHERE short_id = %s AND user_id = %s;", (shortid, session["user"]["id"]))
    comment_count = int(cursor.fetchall()[0]["comment_count"])

    if comment_count >= 40:
        return "TooManyComments"

    mycomment = Comment(text=request.args.get("txt"), author=session["user"]["id"], short_id=int(shortid), parent=parent_comment)

    with app.app_context():
        mycomment.save()

    for comment in SQLAlchemy_session.query(Comment).order_by(Comment.path):
        print('{}{}: {}'.format('  ' * comment.level(), comment.author, comment.text))

    return "Success"

@app.route("/if_liked_post")
def liked_post_page():
    if "user" not in session:
        return "NotLoggedIn"

    mycursor = mysql.connection.cursor()

    mycursor.execute("SELECT * FROM likes WHERE short_id = %s AND user_id = %s;", (str(request.args.get("id")), str(session["user"]["id"])))

    myresult = mycursor.fetchall()

    for _ in myresult:
        return "true"

    return "false"

@app.route("/cleanup")
def cleanup_page():
    entries_deleted = delete_non_existent_files_from_shorts()
    return "<h2>Cleanup complete. " + str(entries_deleted) + " entries deleted.</h2>"

@app.route("/")
def index_page():
    logged_in = "username" in session

    cur = mysql.connection.cursor()
    if logged_in:
        cur.execute(
            "SELECT p.id, title, description, url, user_id, date_uploaded, MIN(f.id) followid, MIN(follower_id) follower_id, following_id, (SELECT count(*) FROM `likes` WHERE short_id = p.id) likes, (SELECT username FROM `users` WHERE id = p.user_id) username FROM shorts p INNER JOIN follows f ON (f.following_id = p.user_id) WHERE f.follower_id = %s OR p.user_id = %s GROUP BY p.id ORDER BY p.id DESC LIMIT 20;",
            (str(session["user"]["id"]), str(session["user"]["id"]),)
        )

        rv = cur.fetchall()

        instances = json.loads(requests.get("https://raw.githubusercontent.com/vidzy-social/vidzy-social.github.io/main/instancelist.json", timeout=20).text)

        for i in instances:
            if requests.get(i + "/api/vidzy", timeout=20).text != "vidzy":
                print("Skipped instance: " + i)
            else:
                r = json.loads(requests.get(i + "/api/live_feed?startat=0", timeout=20).text)
                for c in r:
                    c["url"] = i + "/static/uploads/" + c["url"]
                    rv = rv + (c,)

        rv = sorted(rv, key=itemgetter('id'), reverse=True)

        '''
        # Random chance for a video to swap with another video within 5 positions of itself
        for i in range(len(rv)):
            if random.random() < 0.2:  # 20% chance to swap
                # Limit swap range to be within 5 positions
                swap_index = random.randint(max(i - 5, 0), min(i + 5, len(rv) - 1))
                if swap_index != i:  # Avoid swapping with the same item
                    rv[i], rv[swap_index] = rv[swap_index], rv[i]
        '''

        grouped_by_date = defaultdict(lambda: defaultdict(list))

        for video in rv:
            date = video['date_uploaded']
            if isinstance(date, str):
                date = datetime.strptime(date, "%a, %d %b %Y %H:%M:%S GMT").date()
            
            if video['description'] is None:
                tags = []
            else:
                tags = [word for word in video['description'].split() if word.startswith('#')]

            for tag in tags:
                grouped_by_date[date][tag].append(video)

        for date, tags in grouped_by_date.items():
            for tag, videos in tags.items():
                random.shuffle(videos)

        final_videos = []
        for date in sorted(grouped_by_date.keys()):  # Sort by date
            for tag in sorted(grouped_by_date[date].keys()):  # Sort by tag within each date
                final_videos.extend(grouped_by_date[date][tag])



        return render_template('index.html', shorts=final_videos, session=session, logged_in = logged_in)
    return explore_page()

@app.route("/public/remote")
def public_remote_page():
    logged_in = "username" in session

    instances = json.loads(requests.get("https://raw.githubusercontent.com/vidzy-social/vidzy-social.github.io/main/instancelist.json", timeout=20).text)

    rv = tuple()

    for i in instances:
        if requests.get(i + "/api/vidzy", timeout=20).text != "vidzy":
            print("Skipped instance: " + i)
        else:
            r = json.loads(requests.get(i + "/api/live_feed/full", timeout=20).text)
            for c in r:
                c["url"] = i + "/static/uploads/" + c["url"]
                rv = rv + (c,)

    rv = sorted(rv, key=itemgetter('id'), reverse=True)

    rv = rv[:10]

    return render_template('index.html', shorts=rv, session=session, logged_in = logged_in)

@app.route("/settings", methods=['POST', 'GET'])
def settings_page():
    if "username" in request.form:
        cursor = mysql.connection.cursor()
        cursor.execute("UPDATE `users` SET `username` = %s WHERE (`id` = %s);", (request.form["username"], session["user"]["id"]))
        mysql.connection.commit()

        cursor.execute("UPDATE `users` SET `email` = %s WHERE (`id` = %s);", (request.form["email"], session["user"]["id"]))
        mysql.connection.commit()

        session.clear()

        return redirect("login")

    return render_template('settings.html', username=session["user"]["username"], email=session["user"]["email"])

@app.route("/shorts/<short>/analytics/public")
def video_publicanalytics(short):
    if "user" not in session:
        return "<script>window.location.href='/login';</script>"

    cur = mysql.connection.cursor()

    cur.execute("SELECT *, (SELECT count(*) FROM `likes` WHERE short_id = p.id) like_count FROM `shorts` p  WHERE (`id` = %s);", (short,))
    short = cur.fetchall()[0]

    return render_template('public_vid_analytics.html', session=session, short=short, time_uploaded=time)

@app.route("/shorts/<short_id>/analytics/private")
def video_privateanalytics(short_id):
    if "user" not in session:
        return "<script>window.location.href='/login';</script>"

    cur = mysql.connection.cursor()

    cur.execute("SELECT *, (SELECT count(*) FROM `likes` WHERE short_id = p.id) like_count FROM `shorts` p  WHERE (`id` = %s);", (short_id,))
    short = cur.fetchall()
    if len(short) == 0:
        return "Video not found."
    short = short[0]

    if session["user"]["id"] != short["user_id"]:
        return "<script>window.location.href='/';</script>"

    return render_template('private_vid_analytics.html', session=session, short=short)

import admin

@app.route("/search")
def search_page():
    if "username" not in session:
        return "<script>window.location.href='/login';</script>"

    query = request.args.get('q')

    cur = mysql.connection.cursor()
    cur.execute("SELECT *, (SELECT count(*) FROM `likes` WHERE short_id = p.id) likes FROM shorts p INNER JOIN follows f ON (f.following_id = p.user_id) WHERE title LIKE %s ORDER BY f.follower_id = %s, p.user_id = %s LIMIT 20;", ("%" + query + "%", str(session["user"]["id"]), str(session["user"]["id"])))
    rv = cur.fetchall()

    return render_template('search.html', shorts=rv, session=session, query=query, logged_in = "username" in session)

@app.route("/explore")
def explore_page():
    logged_in = "username" in session

    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT *, (SELECT count(*) FROM `likes` p WHERE p.short_id = shorts.id) likes FROM shorts ORDER BY likes DESC LIMIT 3;")
    rv = cur.fetchall()

    return render_template('explore.html', shorts=rv, session=session, logged_in = logged_in, page="explore")

@app.route("/livefeed")
def livefeed_page():
    logged_in = "username" in session

    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT *, (SELECT count(*) FROM `likes` p WHERE p.short_id = shorts.id) likes FROM shorts ORDER BY id DESC LIMIT 3;")
    rv = cur.fetchall()

    return render_template('explore.html', shorts=rv, session=session, logged_in = logged_in, page="livefeed")

@app.route("/tags/<tag>")
def tag_page(tag):
    logged_in = "username" in session

    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT *, (SELECT count(*) FROM `likes` p WHERE p.short_id = shorts.id) likes FROM shorts WHERE description LIKE %s ORDER BY id DESC LIMIT 3;", ('%#' + tag + '%',))
    rv = cur.fetchall()

    return render_template('explore.html', shorts=rv, session=session, logged_in = logged_in, page="livefeed")

@app.route("/users/<user>")
def profile_page(user):
    if "@" in user:
        if user.split("@")[1] != str(urlparse(request.base_url).netloc):
            return remote_profile_page(user)
        return remote_profile_page(user) # TEMPORARY FOR TESTING
        #user = user.split("@")[0]

    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM users WHERE username=%s;", (user, ))
    user = cur.fetchall()[0]

    cur.execute("SELECT * FROM shorts WHERE user_id=%s;", (str(user["id"]), ))
    latest_short_list = cur.fetchall()

    cur.execute("SELECT count(*) c FROM shorts WHERE user_id=%s;", (str(user["id"]), ))
    shorts_count = cur.fetchall()[0]["c"]

    if "user" in session:
        cur.execute("SELECT * FROM follows WHERE follower_id=%s AND following_id=%s;", (str(session["user"]["id"]), str(user["id"])))
        following = False
        for _ in cur.fetchall():
            following = True
    else:
        following = False

    cur.execute("SELECT count(*) c FROM follows WHERE following_id=%s;", (str(user["id"]),))
    for _ in cur.fetchall():
        follower_count = _["c"]

    return render_template('profile.html', user=user, session=session, latest_short_list=latest_short_list, following=following, follower_count=follower_count, shorts_count=shorts_count)

def remote_vidzy_profile_page(user):
    print("http://" + user.split("@")[1] + "/api/users/" + user.split("@")[0])
    r = requests.get("http://" + user.split("@")[1] + "/api/users/" + user.split("@")[0], timeout=20).text
    data = json.loads(r)
    if not "followers" in data:
        data["followers"] = 0
    return render_template("remote_user.html", shorts=data["videos"], followers_count=data["followers"], user_info=data, full_username=user, logged_in = "username" in session)

@app.route("/remote_user/<user>")
def remote_profile_page(user):
    if requests.get("http://" + user.split("@")[1] + "/api/vidzy", timeout=20).text == "vidzy":
        print("Vidzy instance detected")
        return remote_vidzy_profile_page(user)

    variant = ""

    try:
        outbox = json.loads(requests.get("https://" + user.split("@")[1] + "/users/" + user.split("@")[0] + "/outbox?page=true", timeout=20).text)
        variant = "mastodon"
    except json.decoder.JSONDecodeError:
        outbox = json.loads(requests.get("https://" + user.split("@")[1] + "/accounts/" + user.split("@")[0] + "/outbox?page=1", headers={"Accept":"application/activity+json"}, timeout=20).text)
        variant = "peertube"

    shorts = []

    for post in outbox["orderedItems"]:
        if isinstance(post["object"], dict):
            if variant == "peertube":
                for i in post["object"]["url"][1]["tag"]:
                    if "mediaType" in i:
                        if i["mediaType"] == "video/mp4":
                            shorts.append( {"id": 1, "url": i["href"], "username": user, "title": "test"} )
                            break
            else:
                if len(post["object"]["attachment"]) > 0:
                    if post["object"]["attachment"][0]["mediaType"].startswith("video"):
                        shorts.append( { "id": 1, "url": post["object"]["attachment"][0]["url"], "username": user, "title": cleanhtml(post["object"]["content"]) } )

    if variant == "mastodon":
        followers_count = json.loads(
            requests.get("https://" + user.split("@")[1] + "/users/" + user.split("@")[0] + "/followers", headers={"Accept":"application/activity+json"}, timeout=20).text
        )["totalItems"]
    else:
        followers_count = 0

    if variant == "mastodon":
        user_info = json.loads(
            requests.get("https://" + user.split("@")[1] + "/users/" + user.split("@")[0], headers={"Accept":"application/activity+json"}, timeout=20).text
        )
    else:
        user_info = {}

    return render_template("remote_user.html", shorts=shorts, followers_count=followers_count, user_info=user_info, full_username=user, logged_in = "username" in session)


@app.route("/hcard/users/<guid>")
def hcard_page(guid):
    user = bytes.fromhex(guid).decode('utf-8')

    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM users WHERE username=%s;", (user, ))
    user = cur.fetchall()[0]

    cur.execute("SELECT * FROM shorts WHERE user_id=%s;", (str(user["id"]), ))
    latest_short_list = cur.fetchall()

    return render_template('profile_hcard.html', user=user, session=session, latest_short_list=latest_short_list, guid=guid)


@app.route("/users/<user>/feed")
def profile_feed_page(user):
    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM users WHERE username=%s;", (user, ))
    user = cur.fetchall()[0]

    cur.execute("SELECT * FROM shorts WHERE user_id=%s;", (str(user["id"]), ))
    latest_short_list = cur.fetchall()

    resp = make_response(render_template(
        'profile_feed.xml', user=user, session=session, latest_short_list=latest_short_list))
    resp.headers['Content-type'] = 'text/xml; charset=utf-8'
    return resp


@app.route("/shorts/<short>")
def short_page(short):
    if "username" not in session:
        return "<script>window.location.href='/login';</script>"

    cur = mysql.connection.cursor()
    cur.execute("SELECT *, (SELECT count(*) FROM `likes` WHERE short_id = p.id) likes FROM shorts p WHERE id = %s;", (short,))
    rv = cur.fetchall()[0]

    return render_template('short.html', short=rv, session=session, logged_in = "username" in session)


@app.route('/static/<path:path>')
def send_static(path):
    if path.startswith("uploads/https://"):
        return redirect(path[8:], code=302)
    return send_from_directory('static', path)


@app.route('/login', methods=['POST', 'GET'])
def login_page():
    if "username" in session:
        return "<script>window.location.href='/';</script>"

    if "username" in request.form:
        username = request.form["username"]
        password = request.form["password"]

        mycursor = mysql.connection.cursor()

        mycursor.execute(
            "SELECT * FROM users WHERE username = %s;", (username,))

        myresult = mycursor.fetchall()

        if len(myresult) == 0:
            return "<br><h1 style='text-align:center'>User doesn't exist. Would you like to <a href='/register'>sign up?</a></h1>"

        for x in myresult:
            if x["password"] == hashlib.sha256(password.encode()).hexdigest():
                session["username"] = username
                session["id"] = x["id"]
                session["user"] = x
                return "<script>window.location.href='/';</script>"
            return "<script>window.location.href='/login';</script>"
    else:
        return render_template("login.html")

@app.route('/logout')
def logout():
    session.clear()
    return app.make_response(redirect(url_for("login_page")))

@app.route('/register', methods =['GET', 'POST'])
def register():
    if "username" in session:
        return "<script>window.location.href='/';</script>"

    msg = ''
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form and 'email' in request.form:
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        cursor = mysql.connection.cursor()
        cursor.execute('SELECT * FROM users WHERE username = %s', (username, ))
        account = cursor.fetchone()
        if account:
            msg = 'Account already exists!'
        elif not re.match(r'[^@]+@[^@]+\.[^@]+', email):
            msg = 'Invalid email address!'
        elif not re.match(r'[A-Za-z0-9]+', username):
            msg = 'Username must contain only characters and numbers!'
        elif not username or not password or not email:
            msg = 'Please fill out the form!'
        else:
            cursor.execute('INSERT INTO users (`username`, `password`, `email`) VALUES (%s, %s, %s)', (username, hashlib.sha256(password.encode()).hexdigest(), email, ))
            mysql.connection.commit()
            msg = 'You have successfully registered! <a href="/login">Click here to login</a>'
    elif request.method == 'POST':
        msg = 'Please fill out the form!'
    return render_template('register.html', msg = msg)


@app.route('/users/<username>/inbox', methods=['POST'])
def user_inbox(username):
    if username != "testuser":
        abort(404)

    app.logger.info(request.headers)
    app.logger.info(request.data)

    return Response("", status=202)

@app.route('/.well-known/webfinger')
def webfinger():
    instance_url = str(urlparse(request.base_url).scheme) + "://" + str(urlparse(request.base_url).netloc)

    resource = request.args.get('resource')

    if resource != "acct:testuser@" + str(urlparse(request.base_url).netloc):
        abort(404)

    response = make_response({
        "subject": "acct:testuser@" + str(urlparse(request.base_url).netloc),
        "links": [
            {
                "rel": "self",
                "type": "application/activity+json",
                "href": instance_url + "/users/testuser"
            }
        ]
    })

    # Servers may discard the result if you do not set the appropriate content type
    response.headers['Content-Type'] = 'application/jrd+json'

    return response

@app.route('/activitypub/actor/<user>')
def activitypub_actor(user):
    info = {
        "@context": [
            "https://www.w3.org/ns/activitystreams",
            "https://w3id.org/security/v1"
        ],

        "id": request.base_url,
        "type": "Person",
        "following": "https://mastodon.jgarr.net/following",
        "followers": "https://mastodon.jgarr.net/followers",
        "featured": "https://mastodon.jgarr.net/featured",
        "inbox": "https://mastodon.jgarr.net/inbox",
        "outbox": "https://mastodon.jgarr.net/outbox",
        "preferredUsername": user,
        "name": "Justin Garrison",
        "summary": "Static mastodon server example.",
        "url": "https://justingarrison.com",
        "manuallyApprovesFollowers": True,
        "discoverable": True,
        "published": "2000-01-01T00:00:00Z",
    }

    resp = Response(json.dumps(info))
    resp.headers['Content-Type'] = 'application/json'
    return resp

####################################
############ API ROUTES ############

@app.route('/api/v1/instance')
def instance_info():
    info = {
        "uri": str(urlparse(request.base_url).scheme) + "://" + str(urlparse(request.base_url).netloc),
        "title": "Vidzy",
        "short_description": "The testing server operated by Vidzy",
        "description": "",
        "version": VIDZY_VERSION
    }

    resp = Response(json.dumps(info))
    resp.headers['Content-Type'] = 'application/json'
    return resp

@app.route("/api/search")
def api_search_page():
    query = request.args.get('q')

    cur = mysql.connection.cursor()
    cur.execute("SELECT p.id, p.title, p.user_id, p.url, p.description, p.date_uploaded, (SELECT count(*) FROM `likes` WHERE short_id = p.id) likes FROM shorts p INNER JOIN follows f ON (f.following_id = p.user_id) WHERE title LIKE %s LIMIT 20;", ("%" + query + "%", ))
    rv = cur.fetchall()

    for row in rv:
        row["url"] = str(urlparse(request.base_url).scheme) + "://" + str(urlparse(request.base_url).netloc) + "/static/uploads/" + row["url"]

    return jsonify(rv)

@app.route("/api/users/<user>")
def api_user_page(user):
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, username, bio, (SELECT count(*) FROM `follows` WHERE following_id = u.id) followers FROM `users` u WHERE (`username` = %s);", (user,))
    rv = cur.fetchall()[0]

    cur.execute(
        "SELECT p.id, p.title, p.user_id, p.url, p.description, p.date_uploaded, (SELECT count(*) FROM `likes` WHERE short_id = p.id) likes FROM shorts p WHERE user_id=%s;",
        (rv["id"],)
    )
    shorts = cur.fetchall()

    for row in shorts:
        row["url"] = str(urlparse(request.base_url).scheme) + "://" + str(urlparse(request.base_url).netloc) + "/static/uploads/" + row["url"]

    rv["videos"] = shorts

    return jsonify(rv)

@app.route("/api/vidzy")
def api_vidzy_page():
    return "vidzy"

@app.route("/api/live_feed")
def api_livefeed_page():
    start_at = int(request.args.get('startat'))

    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT date_uploaded, description, id, title, url, user_id, (SELECT count(*) FROM `likes` p WHERE p.short_id = shorts.id) likes FROM shorts ORDER BY id DESC LIMIT %s OFFSET %s;", (start_at+2,start_at))
    rv = cur.fetchall()

    nh3_tags = set() # Empty set

    for r in rv:
        r["title"] = nh3.clean(r["title"], tags=nh3_tags)
        if "description" in r:
            if r["description"] is not None:
                r["description"] = nh3.clean(r["description"], tags=nh3_tags)
        r["url"] = nh3.clean(r["url"], tags=nh3_tags)

    return jsonify(rv)

@app.route("/api/live_feed/full")
def api_livefeed_full_page():

    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT date_uploaded, description, id, title, url, user_id, (SELECT count(*) FROM `likes` p WHERE p.short_id = shorts.id) likes FROM shorts ORDER BY id DESC LIMIT 20;")
    rv = cur.fetchall()

    nh3_tags = set() # Empty set

    for r in rv:
        r["title"] = nh3.clean(r["title"], tags=nh3_tags)
        if "description" in r:
            if r["description"] is not None:
                r["description"] = nh3.clean(r["description"], tags=nh3_tags)
        r["url"] = nh3.clean(r["url"], tags=nh3_tags)

    return jsonify(rv)

@app.route("/api/explore")
def api_explore_page():
    start_at = int(request.args.get('startat'))

    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT id, title, url, user_id, date_uploaded, description, tags, (SELECT count(*) FROM `likes` p WHERE p.short_id = shorts.id) likes FROM shorts ORDER BY likes DESC LIMIT %s OFFSET %s;", (start_at+2,start_at))
    rv = cur.fetchall()

    nh3_tags = set() # Empty set

    for r in rv:
        r["title"] = nh3.clean(r["title"], tags=nh3_tags)
        if "description" in r:
            if r["description"] is not None:
                r["description"] = nh3.clean(r["description"], tags=nh3_tags)
        if "tags" in r:
            if r["tags"] is not None:
                r["tags"] = nh3.clean(r["tags"], tags=nh3_tags)
                r["tags"] = r["tags"].split(",")
        r["url"] = nh3.clean(r["url"], tags=nh3_tags)

    return jsonify(rv)

@app.route("/api/get_most_popular_tags")
def api_get_popular_tags():
    cur = mysql.connection.cursor()
    cur.execute("""
SELECT tag, COUNT(*) AS tag_count
FROM (
    SELECT REGEXP_SUBSTR(description, '#[A-Za-z0-9_]+') AS tag
    FROM shorts
    JOIN (SELECT 1 AS n UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 
          UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9 UNION SELECT 10) numbers
    ON CHAR_LENGTH(description)
    -CHAR_LENGTH(REPLACE(description, '#', '')) >= n - 1
) AS tags
WHERE tag != '' AND tag IS NOT NULL
GROUP BY tag
ORDER BY tag_count DESC
LIMIT 3;
    """)
    rv = cur.fetchall()

    return jsonify(rv)

############ API ROUTES ############
####################################

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if 'username' not in session:
        return "<script>window.location.href='/login';</script>"

    if "ALLOW_UPLOADS" in vidzyconfig.config:
        if vidzyconfig.config["ALLOW_UPLOADS"] is False:
            return "This instance does not allow uploading videos"

    video_description = ""
    if request.form.get("description") != None and request.form.get("tags") != None:
        video_description = request.form.get("description")
        video_description += "  " + request.form.get("tags")

    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        # If the user does not select a file, the browser submits an
        # empty file without a filename.
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)

        if file.content_length > 99 * 1024 * 1024:  # 99MB in bytes
            return 'File is too large. Please upload a file smaller than 99MB.'
        
        if file and allowed_file(file.filename):
            filename = datetime.today().strftime('%Y%m%d') + secure_filename(file.filename) + "__" + str(random.randrange(0,9999))
            if s3_enabled == 'True':
                new_filename = uuid.uuid4().hex + '.' + file.filename.rsplit('.', 1)[1].lower()

                bucket_name = app.config['S3_BUCKET_NAME']

                s3_session = boto3.Session(
                    aws_access_key_id=app.config['AWS_ACCESS_KEY_ID'],
                    aws_secret_access_key=app.config['AWS_SECRET_ACCESS_KEY'],
                )
                s3 = s3_session.resource('s3')
                s3.Bucket(bucket_name).upload_fileobj(file, new_filename)

                s3_fileurl = urllib.parse.urljoin(app.config['S3_PUBLIC_URL'], new_filename)

                cur = mysql.connection.cursor()

                cur.execute( """INSERT INTO shorts (title, url, user_id, date_uploaded, description, time_uploaded) VALUES (%s,%s,%s,%s,%s,%s)""", (request.form.get("title"), s3_fileurl, str(session["user"]["id"]), datetime.now().strftime('%Y-%m-%d'), video_description, datetime.now().strftime('%H:%M:%S')) )
                mysql.connection.commit()
            else:
                temp_filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_video.' + file.filename.rsplit('.', 1)[1].lower())
                file.save(temp_filepath)
                try:
                    video = VideoFileClip(temp_filepath)
                    duration = video.duration  # Duration in seconds
                    if duration > 180:
                        video.close()
                        os.remove(temp_filepath)
                        return 'Video duration exceeds 3 minutes. Please upload a video that is less than 3 minutes.'
                        return redirect(request.url)
                except Exception as e:
                    video.close()
                    os.remove(temp_filepath)
                    return f"Error processing video: {e}"
                    return redirect(request.url)
                finally:
                    video.close()
                time.sleep(1)

                if vidzyconfig.config["use_absolute_upload_path"]:
                    project_folder = vidzyconfig.config["vidzy_absolute_path"]
                    os.rename(temp_filepath, os.path.join(os.path.join(project_folder + '/' + app.config['UPLOAD_FOLDER'], filename)))
                else:
                    os.rename(temp_filepath, os.path.join(app.config['UPLOAD_FOLDER'], filename))


                cur = mysql.connection.cursor()

                cur.execute( """INSERT INTO shorts (title, url, user_id, date_uploaded, description, time_uploaded) VALUES (%s,%s,%s,%s,%s,%s)""", (request.form.get("title"), filename, str(session["user"]["id"]), datetime.now().strftime('%Y-%m-%d'), video_description, datetime.now().strftime('%H:%M:%S')) )
                mysql.connection.commit()

            return redirect(url_for('index_page'))
    return render_template("upload_video.html")

@app.route("/onboarding")
def onboarding_page():
    return render_template("onboarding.html")

@app.route('/follow')
def follow():
    following_id = str(request.args.get("id"))


    cur = mysql.connection.cursor()


    cur.execute("SELECT * FROM follows WHERE following_id = %s AND follower_id = %s;", (following_id, str(session["user"]["id"])))

    myresult = cur.fetchall()

    for _ in myresult:
        return "Already following"


    cur.execute("""INSERT INTO follows (follower_id, following_id) VALUES (%s,%s)""", (str(session["user"]["id"]), following_id))
    mysql.connection.commit()

    return "Done"

@app.route('/unfollow')
def unfollow():
    following_id = str(request.args.get("id"))


    cur = mysql.connection.cursor()


    cur.execute("SELECT * FROM follows WHERE following_id = %s AND follower_id = %s;", (following_id, str(session["user"]["id"])))

    myresult = cur.fetchall()

    following = False
    for _ in myresult:
        following = True

    if not following:
        return "Not currently following user"

    cur.execute("""DELETE FROM `follows` WHERE `follower_id` = %s AND `following_id` = %s;""", (str(session["user"]["id"]), following_id))
    mysql.connection.commit()

    return "Done"

def round_to_multiple(number, multiple):
    return multiple * round(number / multiple)

def floor_to_multiple(number, multiple):
    return multiple * math.ceil(number / multiple)

@app.route("/about")
def about():
    cur = mysql.connection.cursor()
    cur.execute("SELECT count(*) total_accounts FROM `users`;")
    total_accounts = floor_to_multiple(cur.fetchall()[0]["total_accounts"], 5)

    return render_template('about.html', instance_domain=urlparse(request.base_url).hostname, total_accounts=total_accounts)

############## ERRORS ##############
####################################

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def page_not_found(e):
    return render_template('500.html'), 500

def create_app():
    return app

if __name__ == "__main__":
    app.run(host=app.config["HOST"], debug=True)
