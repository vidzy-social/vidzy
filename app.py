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

# Routes
import routes.admin
import routes.demos
import routes.comments
import routes.errors
import routes.account
import routes.api
import routes.feeds
import routes.shorts
import routes.interactions
import routes.users

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


@app.route("/search")
def search_page():
    if "username" not in session:
        return "<script>window.location.href='/login';</script>"

    query = request.args.get('q')

    cur = mysql.connection.cursor()
    cur.execute("SELECT *, (SELECT count(*) FROM `likes` WHERE short_id = p.id) likes FROM shorts p INNER JOIN follows f ON (f.following_id = p.user_id) WHERE title LIKE %s ORDER BY f.follower_id = %s, p.user_id = %s LIMIT 20;", ("%" + query + "%", str(session["user"]["id"]), str(session["user"]["id"])))
    rv = cur.fetchall()

    return render_template('search.html', shorts=rv, session=session, query=query, logged_in = "username" in session)

@app.route("/hcard/users/<guid>")
def hcard_page(guid):
    user = bytes.fromhex(guid).decode('utf-8')

    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM users WHERE username=%s;", (user, ))
    user = cur.fetchall()[0]

    cur.execute("SELECT * FROM shorts WHERE user_id=%s;", (str(user["id"]), ))
    latest_short_list = cur.fetchall()

    return render_template('profile_hcard.html', user=user, session=session, latest_short_list=latest_short_list, guid=guid)

@app.route('/static/<path:path>')
def send_static(path):
    if path.startswith("uploads/https://"):
        return redirect(path[8:], code=302)
    return send_from_directory('static', path)

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

def create_app():
    return app

if __name__ == "__main__":
    app.run(host=app.config["HOST"], debug=True)
