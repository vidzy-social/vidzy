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

