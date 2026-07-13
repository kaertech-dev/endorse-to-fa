# config.py

import os
import pymysql.cursors

DB_HOST = os.getenv("DB_HOST", "192.168.1.38")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "labeling")
DB_PASS = os.getenv("DB_PASSWORD", "labeling")
DB_NAME = os.getenv("DB_NAME", "fa")


def get_db_connection():
    """Open a new connection to the fa database."""
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )

def get_connect_all():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )