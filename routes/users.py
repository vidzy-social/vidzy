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
from app import app, session, mysql

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
