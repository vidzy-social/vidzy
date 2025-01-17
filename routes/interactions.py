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
