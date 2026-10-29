
from datetime import datetime, timezone
import math
import secrets
from copy import deepcopy

from bson import ObjectId
from flask import Blueprint, request, jsonify, session
from pymongo.errors import DuplicateKeyError

from app.db import db


surveys_bp = Blueprint("surveys", __name__, url_prefix="/api/surveys")


def get_owned_survey(survey_id, user_id):
    """查找当前用户创建的问卷。"""
    if not ObjectId.is_valid(survey_id):
        return None, (jsonify({"error": "问卷 ID 格式不正确"}), 400)

    survey = db.surveys.find_one({
        "_id": ObjectId(survey_id),
        "creator_id": user_id,
    })

    if survey is None:
        return None, (
            jsonify({"error": "问卷不存在或你没有管理权限"}),
            404,
        )

    return survey, None


def serialize_survey(survey):
    """将问卷文档转换成可以返回的 JSON 数据。"""
    created_at = survey.get("created_at")
    updated_at = survey.get("updated_at")
    deadline = survey.get("deadline")

    return {
        "survey_id": str(survey["_id"]),
        "title": survey.get("title", ""),
        "description": survey.get("description", ""),
        "anonymous": survey.get("anonymous", False),
        "status": survey.get("status", "draft"),
        "share_code": survey.get("share_code", ""),
        "deadline": deadline.isoformat() if deadline else None,
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


def serialize_question_snapshot(question):
    """生成完整的问卷题目快照，不依赖题库后续版本的变化。"""
    question_id = question.get("_id")
    if question_id is None:
        question_id = question.get("question_id")

    if question_id is None:
        raise ValueError("题目缺少 ID，无法生成发布快照")

    snapshot = {
        # 保留两种 ID 字段，兼容不同的读取逻辑。
        "_id": str(question_id),
        "question_id": str(question_id),
        "title": question.get("title", ""),
        "type": question.get("type", ""),
        "required": question.get("required", False),
        "options": deepcopy(question.get("options", [])),
        "order": question.get("order", 0),
        "validation": deepcopy(question.get("validation", {})),
        "jump_rules": deepcopy(question.get("jump_rules", [])),
    }

    for field in ("description", "placeholder"):
        if field in question:
            snapshot[field] = deepcopy(question[field])

    # 保存题库来源，明确问卷使用的是哪个题目版本。
    if "library_question_id" in question:
        value = question["library_question_id"]
        snapshot["library_question_id"] = (
            str(value) if isinstance(value, ObjectId) else value
        )

    if "question_key" in question:
        snapshot["question_key"] = question["question_key"]

    if "question_version" in question:
        snapshot["question_version"] = question["question_version"]
        snapshot["version"] = question["question_version"]
    elif "version" in question:
        snapshot["version"] = question["version"]

    if "parent_version_id" in question:
        value = question["parent_version_id"]
        snapshot["parent_version_id"] = (
            str(value) if isinstance(value, ObjectId) else value
        )

    return snapshot


def get_survey_question_snapshots(survey):
    """
    获取问卷题目。
    优先使用发布快照；旧数据没有快照时，回退到 questions 集合。
    """
    snapshots = survey.get("question_snapshots")

    if isinstance(snapshots, list):
        return deepcopy(snapshots)

    questions = list(
        db.questions.find({
            "survey_id": str(survey["_id"]),
        }).sort("order", 1)
    )

    return [
        serialize_question_snapshot(question)
        for question in questions
    ]


@surveys_bp.post("")
def create_survey():
    """创建一份新问卷。"""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求内容必须是 JSON"}), 400

    title = data.get("title")
    if not isinstance(title, str):
        return jsonify({"error": "问卷标题必须是字符串"}), 400

    title = title.strip()
    if not title:
        return jsonify({"error": "问卷标题不能为空"}), 400

    if len(title) > 100:
        return jsonify({"error": "问卷标题不能超过 100 个字符"}), 400

    description = data.get("description", "")
    if not isinstance(description, str):
        return jsonify({"error": "问卷描述必须是字符串"}), 400

    anonymous = data.get("anonymous", False)
    if not isinstance(anonymous, bool):
        return jsonify({"error": "anonymous 必须是布尔值"}), 400

    now = datetime.now(timezone.utc)

    survey = {
        "creator_id": user_id,
        "title": title,
        "description": description.strip(),
        "anonymous": anonymous,
        "status": "draft",
        "share_code": secrets.token_urlsafe(8),
        "deadline": None,
        "created_at": now,
        "updated_at": now,
    }

    for _ in range(3):
        try:
            result = db.surveys.insert_one(survey)
            break
        except DuplicateKeyError:
            survey["share_code"] = secrets.token_urlsafe(8)
    else:
        return jsonify({"error": "生成分享码失败，请重试"}), 500

    survey["_id"] = result.inserted_id

    return jsonify({
        "message": "问卷创建成功",
        **serialize_survey(survey),
    }), 201


@surveys_bp.get("")
def list_my_surveys():
    """获取当前登录用户创建的问卷列表。"""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    cursor = db.surveys.find(
        {"creator_id": user_id}
    ).sort("created_at", -1)

    surveys = [serialize_survey(survey) for survey in cursor]

    return jsonify({
        "count": len(surveys),
        "surveys": surveys,
    }), 200


@surveys_bp.post("/<survey_id>/publish")
def publish_survey(survey_id):
    """发布草稿问卷，并保存题目快照。"""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    survey, error_response = get_owned_survey(survey_id, user_id)
    if error_response:
        return error_response

    if survey.get("status") != "draft":
        return jsonify({"error": "只有草稿问卷才能发布"}), 400

    questions = list(
        db.questions.find({
            "survey_id": survey_id,
        }).sort("order", 1)
    )

    if not questions:
        return jsonify({"error": "问卷至少需要一道题目才能发布"}), 400

    now = datetime.now(timezone.utc)
    deadline = survey.get("deadline")

    if deadline:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)

        if deadline <= now:
            return jsonify({"error": "截止时间必须晚于当前时间才能发布"}), 400

    question_snapshots = [
        serialize_question_snapshot(question)
        for question in questions
    ]

    # 原子更新：仅允许草稿问卷变为已发布状态。
    result = db.surveys.update_one(
        {
            "_id": survey["_id"],
            "creator_id": user_id,
            "status": "draft",
        },
        {
            "$set": {
                "status": "published",
                "updated_at": now,
                "question_snapshots": question_snapshots,
            }
        },
    )

    if result.modified_count != 1:
        return jsonify({
            "error": "问卷状态已发生变化，请刷新后重试"
        }), 409

    return jsonify({
        "message": "问卷发布成功",
        "survey_id": survey_id,
        "status": "published",
        "share_code": survey["share_code"],
        "share_path": f"/survey/{survey['share_code']}",
        "deadline": deadline.isoformat() if deadline else None,
        "question_count": len(question_snapshots),
    }), 200


@surveys_bp.post("/<survey_id>/close")
def close_survey(survey_id):
    """手动关闭已发布的问卷。"""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    survey, error_response = get_owned_survey(survey_id, user_id)
    if error_response:
        return error_response

    if survey.get("status") != "published":
        return jsonify({"error": "只有已发布的问卷才能关闭"}), 400

    now = datetime.now(timezone.utc)

    result = db.surveys.update_one(
        {
            "_id": survey["_id"],
            "creator_id": user_id,
            "status": "published",
        },
        {
            "$set": {
                "status": "closed",
                "updated_at": now,
            }
        },
    )

    if result.modified_count != 1:
        return jsonify({
            "error": "问卷状态已发生变化，请刷新后重试"
        }), 409

    return jsonify({
        "message": "问卷已关闭",
        "survey_id": survey_id,
        "status": "closed",
    }), 200


@surveys_bp.put("/<survey_id>/deadline")
def set_survey_deadline(survey_id):
    """设置或取消问卷截止时间。"""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    survey, error_response = get_owned_survey(survey_id, user_id)
    if error_response:
        return error_response

    if survey.get("status") != "draft":
        return jsonify({"error": "请在发布前设置截止时间"}), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "deadline" not in data:
        return jsonify({
            "error": "请提供 deadline 字段；设置为空值可取消截止时间"
        }), 400

    raw_deadline = data["deadline"]
    deadline = None

    if raw_deadline is not None:
        if not isinstance(raw_deadline, str):
            return jsonify({
                "error": "deadline 必须是 ISO 8601 日期时间字符串或 null"
            }), 400

        try:
            deadline = datetime.fromisoformat(
                raw_deadline.replace("Z", "+00:00")
            )
        except ValueError:
            return jsonify({
                "error": "截止时间格式不正确，请使用 ISO 8601 格式"
            }), 400

        if deadline.tzinfo is None:
            return jsonify({
                "error": "截止时间必须包含时区，例如 +08:00 或 Z"
            }), 400

        deadline = deadline.astimezone(timezone.utc)

        if deadline <= datetime.now(timezone.utc):
            return jsonify({"error": "截止时间必须晚于当前时间"}), 400

    now = datetime.now(timezone.utc)

    result = db.surveys.update_one(
        {
            "_id": survey["_id"],
            "creator_id": user_id,
            "status": "draft",
        },
        {
            "$set": {
                "deadline": deadline,
                "updated_at": now,
            }
        },
    )

    if result.matched_count != 1:
        return jsonify({
            "error": "问卷状态已发生变化，请刷新后重试"
        }), 409

    return jsonify({
        "message": "截止时间已更新",
        "survey_id": survey_id,
        "deadline": deadline.isoformat() if deadline else None,
    }), 200


@surveys_bp.get("/share/<share_code>")
def get_public_survey(share_code):
    """根据分享码获取已发布问卷及其题目快照。"""
    survey = db.surveys.find_one({"share_code": share_code})

    if survey is None:
        return jsonify({"error": "问卷不存在"}), 404

    if survey.get("status") != "published":
        return jsonify({"error": "问卷尚未发布或已经关闭"}), 403

    now = datetime.now(timezone.utc)
    deadline = survey.get("deadline")

    if deadline is not None:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)

        if deadline <= now:
            return jsonify({"error": "问卷已超过截止时间"}), 403

    question_list = get_survey_question_snapshots(survey)

    return jsonify({
        "survey_id": str(survey["_id"]),
        "title": survey.get("title", ""),
        "description": survey.get("description", ""),
        "anonymous": survey.get("anonymous", False),
        "status": survey.get("status", "published"),
        "deadline": deadline.isoformat() if deadline else None,
        "questions": question_list,
        "message": "问卷可以访问",
    }), 200


@surveys_bp.get("/<survey_id>/stats")
def get_survey_stats(survey_id):
    """获取当前用户创建的问卷统计结果。"""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    survey, error_response = get_owned_survey(survey_id, user_id)
    if error_response:
        return error_response

    questions = get_survey_question_snapshots(survey)

    responses = list(
        db.responses.find({
            "survey_id": str(survey["_id"]),
        })
    )

    question_stats = []

    for question in questions:
        question_id = str(
            question.get("question_id", question.get("_id", ""))
        )
        question_type = question.get("type")
        options = question.get("options", [])

        answer_values = []

        for response in responses:
            response_answers = response.get("answers", [])
            if not isinstance(response_answers, list):
                continue

            for item in response_answers:
                if not isinstance(item, dict):
                    continue

                if item.get("question_id") != question_id:
                    continue

                answer = item.get("answer")

                if answer is None or answer == "":
                    continue

                if isinstance(answer, list) and not answer:
                    continue

                answer_values.append(answer)

        stat = {
            "question_id": question_id,
            "title": question.get("title", ""),
            "type": question_type,
            "answered_count": len(answer_values),
        }

        if question_type in ("single_choice", "multiple_choice"):
            option_stats = []

            for option in options:
                option_id = option.get("option_id")
                count = 0

                for answer in answer_values:
                    if question_type == "single_choice":
                        if answer == option_id:
                            count += 1
                    elif isinstance(answer, list) and option_id in answer:
                        count += 1

                option_stats.append({
                    "option_id": option_id,
                    "text": option.get("text", ""),
                    "count": count,
                })

            stat["options"] = option_stats

        elif question_type == "text":
            stat["answers"] = [
                answer
                for answer in answer_values
                if isinstance(answer, str)
            ]

        elif question_type == "numeric":
            numeric_values = [
                answer
                for answer in answer_values
                if isinstance(answer, (int, float))
                and not isinstance(answer, bool)
                and math.isfinite(answer)
            ]

            stat["numeric_count"] = len(numeric_values)
            stat["average"] = (
                sum(numeric_values) / len(numeric_values)
                if numeric_values
                else None
            )

        question_stats.append(stat)

    return jsonify({
        "survey_id": str(survey["_id"]),
        "title": survey.get("title", ""),
        "response_count": len(responses),
        "questions": question_stats,
    }), 200
