from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo.errors import DuplicateKeyError
from app.db import db

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.post("/register")
def register():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "请求内容必须是 JSON"}), 400

    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify({"error": "用户名和密码必须是字符串"}), 400

    username = username.strip()

    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400

    if len(username) < 3 or len(username) > 30:
        return jsonify({"error": "用户名长度必须为 3 到 30 个字符"}), 400

    if len(password) < 8:
        return jsonify({"error": "密码至少需要 8 个字符"}), 400

    user = {
        "username": username,
        "password_hash": generate_password_hash(password),
    }

    try:
        result = db.users.insert_one(user)
    except DuplicateKeyError:
        return jsonify({"error": "用户名已被注册"}), 409

    return jsonify({
        "message": "注册成功",
        "user_id": str(result.inserted_id),
        "username": username,
    }), 201


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "请求内容必须是 JSON"}), 400

    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify({"error": "用户名和密码必须是字符串"}), 400

    username = username.strip()

    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400

    user = db.users.find_one({"username": username})

    if user is None or not check_password_hash(
        user["password_hash"], password
    ):
        return jsonify({"error": "用户名或密码错误"}), 401

    session["user_id"] = str(user["_id"])
    session["username"] = user["username"]

    return jsonify({
        "message": "登录成功",
        "user_id": str(user["_id"]),
        "username": user["username"],
    }), 200


@auth_bp.post("/logout")
def logout():
    session.clear()
    return jsonify({"message": "退出登录成功"}), 200


@auth_bp.get("/me")
def me():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "logged_in": False,
            "message": "当前未登录",
        }), 200

    return jsonify({
        "logged_in": True,
        "user_id": user_id,
        "username": session.get("username"),
    }), 200
