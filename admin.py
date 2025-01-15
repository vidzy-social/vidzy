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

#######################################################################
########################### ADMIN STUFF ################################

@app.route("/admin")
def admin_panel():
    if "user" not in session:
        return "<script>window.location.href='/login';</script>"

    if not session["user"]["is_admin"] == 1:
        return "<script>window.location.href='/';</script>"

    cur = mysql.connection.cursor()
    cur.execute("SELECT count(*) total_accounts FROM `users`;")
    total_accounts = cur.fetchall()[0]["total_accounts"]

    cur.execute("SELECT count(*) total_shorts FROM `shorts`;")
    total_shorts = cur.fetchall()[0]["total_shorts"]

    cur.execute("SELECT *, (SELECT count(*) FROM `follows` WHERE following_id = u.id) followers FROM `users` u ORDER BY id DESC LIMIT 50;")
    accounts = cur.fetchall()

    cur.execute("SELECT *, (SELECT count(*) FROM `likes` WHERE short_id = p.id) like_count FROM `shorts` p ORDER BY id DESC LIMIT 50;")
    shorts = cur.fetchall()

    videos_on_date_uploaded = {}

    for short in shorts:
        if not short["date_uploaded"] in videos_on_date_uploaded:
            videos_on_date_uploaded[short["date_uploaded"]] = []

        videos_on_date_uploaded[short["date_uploaded"]].append(short)

    videos_on_date_uploaded = collections.OrderedDict(sorted(videos_on_date_uploaded.items()))

    return render_template('admin_panel.html', session=session, total_accounts=total_accounts, accounts=accounts, shorts=shorts, total_shorts=total_shorts, videos_on_date_uploaded=videos_on_date_uploaded)

@app.route("/admin/banform")
def ban_form():
    if "user" not in session:
        return "You are not logged in"
    if not session["user"]["is_admin"] == 1:
        return "You are not an admin"

    userid = request.args.get('user')

    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM `users` WHERE (`id` = %s);", (userid,))
    user = cursor.fetchall()[0]

    if len(user) == 0:
        return "User doesn't exist."

    if user["is_admin"] == 1:
        return "User is an admin. Admins are not bannable through the admin panel."

    return render_template("banform.html", user=user, userid=userid)

@app.route("/admin/ban", methods=['POST'])
def ban_user():
    csrf.protect()

    if "user" not in session:
        return "NotLoggedIn"
    if not session["user"]["is_admin"] == 1:
        return "NotAdmin"

    user = request.form['user']

    cursor = mysql.connection.cursor()
    cursor.execute("DELETE FROM `users` WHERE (`id` = %s);", (user,))
    mysql.connection.commit()

    return redirect("/admin", code=302)

@app.route("/admin/deletevidform")
def delete_vid_form():
    if "user" not in session:
        return "You are not logged in"
    if not session["user"]["is_admin"] == 1:
        return "You are not an admin"

    shortid = request.args.get('short')

    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM `shorts` WHERE (`id` = %s);", (shortid,))
    short = cursor.fetchall()[0]

    if len(short) == 0:
        return "Short doesn't exist."

    return render_template("deletevidform.html", short=short, shortid=shortid)

@app.route("/admin/deletevid", methods=['POST'])
def delete_vid():
    csrf.protect()

    if "user" not in session:
        return "NotLoggedIn"
    if not session["user"]["is_admin"] == 1:
        return "NotAdmin"

    short = request.form['short']

    cursor = mysql.connection.cursor()
    cursor.execute("DELETE FROM `shorts` WHERE (`id` = %s);", (short,))
    mysql.connection.commit()

    return redirect("/admin", code=302)

@app.route("/admin/promoteform")
def promote_form():
    if "user" not in session:
        return "You are not logged in"
    if not session["user"]["is_admin"] == 1:
        return "You are not an admin"

    userid = request.args.get('user')

    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM `users` WHERE (`id` = %s);", (userid,))
    user = cursor.fetchall()[0]

    if len(user) == 0:
        return "User doesn't exist."

    if user["is_admin"] == 1:
        return "User is already an admin."

    return render_template("promoteform.html", user=user, userid=userid)

@app.route("/admin/promote", methods=['POST'])
def promote_user():
    csrf.protect()

    if "user" not in session:
        return "NotLoggedIn"
    if not session["user"]["is_admin"] == 1:
        return "NotAdmin"

    user = request.form['user']

    cursor = mysql.connection.cursor()
    cursor.execute("UPDATE `users` SET `is_admin` = '1' WHERE (`id` = %s);", (user,))
    mysql.connection.commit()

    return redirect("/admin", code=302)

######################### END ADMIN STUFF ##############################
########################################################################
