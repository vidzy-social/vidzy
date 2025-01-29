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
from app import app, session, mysql, Comment, SQLAlchemy_session


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
