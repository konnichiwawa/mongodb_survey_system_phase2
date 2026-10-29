import os

from flask import Flask, jsonify, render_template

from app.db import db, test_connection
from app.routes.auth import auth_bp
from app.routes.surveys import surveys_bp
from app.routes.questions import questions_bp
from app.routes.responses import responses_bp
from app.routes.question_library import question_library_bp


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv(
        "SECRET_KEY",
        "dev-only-change-this-before-submission",
    )

    # 注册后端 API
    app.register_blueprint(auth_bp)
    app.register_blueprint(surveys_bp)
    app.register_blueprint(questions_bp)
    app.register_blueprint(responses_bp)
    app.register_blueprint(question_library_bp)

    # 首页
    @app.get("/")
    def index():
        return render_template("index.html")

    # 登录与注册页面
    @app.get("/login")
    def login_page():
        return render_template("login.html")

    # 创建问卷页面
    @app.get("/create-survey")
    def create_survey_page():
        return render_template("create_survey.html")

    # 添加问卷题目页面
    @app.get("/add-questions")
    def add_questions_page():
        return render_template("add_questions.html")

    # 填写问卷页面
    @app.get("/fill-survey")
    def fill_survey_page():
        return render_template("fill_survey.html")

    # 问卷统计页面
    @app.get("/stats")
    def stats_page():
        return render_template("stats.html")

    # MongoDB 连接检查
    @app.get("/health")
    def health():
        try:
            test_connection()
            return jsonify({
                "status": "ok",
                "mongodb": "connected",
                "database": db.name,
            }), 200
        except Exception:
            app.logger.exception("MongoDB connection check failed")
            return jsonify({
                "status": "error",
                "mongodb": "disconnected",
            }), 503

    return app
