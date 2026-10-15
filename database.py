import pymysql


def get_connection():
    connection = pymysql.connect(
        host="localhost",
        user="root",
        password="",
        database="tower_copter",
        port=3306,
        cursorclass=pymysql.cursors.DictCursor
    )

    return connection