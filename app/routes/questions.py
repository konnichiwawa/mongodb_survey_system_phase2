
from datetime import datetime, timezone
from copy import deepcopy

from bson import ObjectId
from flask import Blueprint, request, jsonify, session

from app.db import db


questions_bp = Blueprint(
    "questions",
    __name__,
    url_prefix="/api/surveys",
)

SUPPORTED_TYPES = {
    "single_choice",
    "multiple_choice",
    "text",
    "numeric",
}


def find_owned_draft_survey(survey_id, user_id):
    """查找当前用户拥有的草稿问卷。"""
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

    if survey.get("status") != "draft":
        return None, (
            jsonify({"error": "目前只能修改草稿问卷中的题目"}),
            400,
        )

    return survey, None


def is_number(value):
    """判断值是否为数字，但不接受布尔值。"""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
    )


def validate_question_data(data):
    """检查题目内容，并返回规范化后的题目字段。"""
    if not isinstance(data, dict):
        return None, "请求内容必须是 JSON 对象"

    title = data.get("title")
    question_type = data.get("type")
    required = data.get("required", True)

    if not isinstance(title, str) or not title.strip():
        return None, "题目内容不能为空"

    title = title.strip()
    if len(title) > 500:
        return None, "题目内容不能超过 500 个字符"

    if question_type not in SUPPORTED_TYPES:
        return None, (
            "题目类型必须是 single_choice、multiple_choice、text 或 numeric"
        )

    if not isinstance(required, bool):
        return None, "required 必须是布尔值"

    options = []

    if question_type in {"single_choice", "multiple_choice"}:
        raw_options = data.get("options")

        if not isinstance(raw_options, list) or len(raw_options) < 2:
            return None, "选择题至少需要两个选项"

        cleaned_options = []

        for option in raw_options:
            if not isinstance(option, str) or not option.strip():
                return None, "选项内容不能为空"

            cleaned_options.append(option.strip())

        if len(set(cleaned_options)) != len(cleaned_options):
            return None, "同一道题的选项不能重复"

        options = [
            {"option_id": str(index + 1), "text": option}
            for index, option in enumerate(cleaned_options)
        ]

    raw_validation = data.get("validation", {})
    if raw_validation is None:
        raw_validation = {}

    if not isinstance(raw_validation, dict):
        return None, "validation 必须是 JSON 对象"

    validation = {}

    if question_type == "multiple_choice":
        min_selections = raw_validation.get("min_selections")
        max_selections = raw_validation.get("max_selections")
        exact_selections = raw_validation.get("exact_selections")

        for name, value in (
            ("min_selections", min_selections),
            ("max_selections", max_selections),
            ("exact_selections", exact_selections),
        ):
            if value is not None:
                if not isinstance(value, int) or isinstance(value, bool):
                    return None, f"{name} 必须是整数"
                if value < 0:
                    return None, f"{name} 不能小于 0"

        option_count = len(options)

        if min_selections is not None and min_selections > option_count:
            return None, "最少选择数量不能超过选项总数"

        if max_selections is not None and max_selections > option_count:
            return None, "最多选择数量不能超过选项总数"

        if (
            min_selections is not None
            and max_selections is not None
            and min_selections > max_selections
        ):
            return None, "最少选择数量不能大于最多选择数量"

        if exact_selections is not None:
            if exact_selections > option_count:
                return None, "固定选择数量不能超过选项总数"

            if (
                min_selections is not None
                and exact_selections < min_selections
            ):
                return None, "固定选择数量不能小于最少选择数量"

            if (
                max_selections is not None
                and exact_selections > max_selections
            ):
                return None, "固定选择数量不能大于最多选择数量"

        if min_selections is not None:
            validation["min_selections"] = min_selections

        if max_selections is not None:
            validation["max_selections"] = max_selections

        if exact_selections is not None:
            validation["exact_selections"] = exact_selections

    elif question_type == "text":
        min_length = raw_validation.get("min_length")
        max_length = raw_validation.get("max_length")

        for name, value in (
            ("min_length", min_length),
            ("max_length", max_length),
        ):
            if value is not None:
                if not isinstance(value, int) or isinstance(value, bool):
                    return None, f"{name} 必须是整数"
                if value < 0:
                    return None, f"{name} 不能小于 0"

        if (
            min_length is not None
            and max_length is not None
            and min_length > max_length
        ):
            return None, "最小字符数不能大于最大字符数"

        if min_length is not None:
            validation["min_length"] = min_length

        if max_length is not None:
            validation["max_length"] = max_length

    elif question_type == "numeric":
        min_value = raw_validation.get("min_value")
        max_value = raw_validation.get("max_value")
        integer = raw_validation.get("integer", False)

        for name, value in (
            ("min_value", min_value),
            ("max_value", max_value),
        ):
            if value is not None and not is_number(value):
                return None, f"{name} 必须是数字"

        if (
            min_value is not None
            and max_value is not None
            and min_value > max_value
        ):
            return None, "最小数值不能大于最大数值"

        if not isinstance(integer, bool):
            return None, "integer 必须是布尔值"

        if min_value is not None:
            validation["min_value"] = min_value

        if max_value is not None:
            validation["max_value"] = max_value

        validation["integer"] = integer

    allowed_validation_keys = {
        "single_choice": set(),
        "multiple_choice": {
            "min_selections",
            "max_selections",
            "exact_selections",
        },
        "text": {"min_length", "max_length"},
        "numeric": {"min_value", "max_value", "integer"},
    }

    unexpected_keys = (
        set(raw_validation.keys())
        - allowed_validation_keys[question_type]
    )

    if unexpected_keys:
        return None, (
            "当前题型不支持这些校验规则："
            + ", ".join(sorted(unexpected_keys))
        )

    jump_rules = data.get("jump_rules", [])
    if jump_rules is None:
        jump_rules = []

    if not isinstance(jump_rules, list):
        return None, "jump_rules 必须是列表"

    normalized_jump_rules = []
    valid_option_ids = {option["option_id"] for option in options}

    for index, rule in enumerate(jump_rules):
        if not isinstance(rule, dict):
            return None, f"第 {index + 1} 条跳转规则必须是 JSON 对象"

        target_question_id = rule.get("target_question_id")
        if (
            not isinstance(target_question_id, str)
            or not ObjectId.is_valid(target_question_id)
        ):
            return None, (
                f"第 {index + 1} 条跳转规则的 target_question_id 不正确"
            )

        normalized_rule = {
            "target_question_id": target_question_id,
        }

        if question_type in {"single_choice", "multiple_choice"}:
            option_id = rule.get("option_id")

            if (
                not isinstance(option_id, str)
                or option_id not in valid_option_ids
            ):
                return None, (
                    f"第 {index + 1} 条跳转规则的 option_id 不属于本题"
                )

            normalized_rule["option_id"] = option_id

        elif question_type == "numeric":
            operator = rule.get("operator")
            value = rule.get("value")

            if operator not in {"eq", "ne", "gt", "gte", "lt", "lte"}:
                return None, (
                    f"第 {index + 1} 条数字跳转规则的 operator 不正确"
                )

            if not is_number(value):
                return None, (
                    f"第 {index + 1} 条数字跳转规则的 value 必须是数字"
                )

            normalized_rule["operator"] = operator
            normalized_rule["value"] = value

        else:
            return None, "文本题暂不支持条件跳转"

        normalized_jump_rules.append(normalized_rule)

    return {
        "title": title,
        "type": question_type,
        "options": options,
        "required": required,
        "validation": validation,
        "jump_rules": normalized_jump_rules,
    }, None


def serialize_question(question):
    """把 MongoDB 题目文档转换成可返回的 JSON 数据。"""
    library_question_id = question.get("library_question_id")
    if isinstance(library_question_id, ObjectId):
        library_question_id = str(library_question_id)

    parent_version_id = question.get("parent_version_id")
    if isinstance(parent_version_id, ObjectId):
        parent_version_id = str(parent_version_id)

    return {
        "question_id": str(question["_id"]),
        "survey_id": question["survey_id"],
        "title": question.get("title", ""),
        "type": question.get("type", ""),
        "options": deepcopy(question.get("options", [])),
        "order": question.get("order", 0),
        "required": question.get("required", True),
        "validation": deepcopy(question.get("validation", {})),
        "jump_rules": deepcopy(question.get("jump_rules", [])),
        "library_question_id": library_question_id,
        "question_key": question.get("question_key"),
        "question_version": question.get("question_version"),
        "parent_version_id": parent_version_id,
    }


def get_next_question_order(survey_id):
    """取得草稿问卷中下一道题目的顺序号。"""
    latest_question = db.questions.find_one(
        {"survey_id": survey_id},
        sort=[("order", -1)],
    )
    return latest_question["order"] + 1 if latest_question else 1


def find_usable_library_question(library_question_id, user_id):
    """查找指定题库版本，并检查当前用户是否有使用权限。"""
    if not ObjectId.is_valid(library_question_id):
        return None, (jsonify({"error": "题库题目版本 ID 格式不正确"}), 400)

    library_question = db.question_library.find_one({
        "_id": ObjectId(library_question_id),
    })

    if library_question is None:
        return None, (jsonify({"error": "题目版本不存在"}), 404)

    if (
        library_question.get("owner_id") != user_id
        and user_id not in library_question.get("shared_with", [])
    ):
        return None, (jsonify({"error": "你没有使用该题目的权限"}), 403)

    return library_question, None


def build_question_from_library(
    survey_id,
    library_question,
    order,
    now,
):
    """把指定题库版本复制为独立的问卷题目。"""
    library_id = str(library_question["_id"])

    parent_version_id = library_question.get("parent_version_id")
    if isinstance(parent_version_id, ObjectId):
        parent_version_id = str(parent_version_id)

    question = {
        "survey_id": survey_id,
        "title": library_question.get("title", ""),
        "type": library_question.get("type", ""),
        "options": deepcopy(library_question.get("options", [])),
        "required": library_question.get("required", True),
        "validation": deepcopy(library_question.get("validation", {})),

        # 跳转目标属于具体问卷，不能沿用题库中的目标 ID。
        "jump_rules": [],

        "order": order,

        # 记录实际使用的题库版本，而不是始终指向最新版本。
        "library_question_id": library_id,
        "question_key": library_question.get("question_key"),
        "question_version": library_question.get("version", 1),
        "parent_version_id": parent_version_id,

        "created_at": now,
        "updated_at": now,
    }

    return question


@questions_bp.post("/<survey_id>/questions")
def create_question(survey_id):
    """为当前用户创建的问卷添加一道题目。"""
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    survey, error_response = find_owned_draft_survey(
        survey_id, user_id
    )
    if error_response:
        return error_response

    data = request.get_json(silent=True)
    fields, error = validate_question_data(data)

    if error:
        return jsonify({"error": error}), 400

    order = get_next_question_order(survey_id)
    now = datetime.now(timezone.utc)

    question = {
        "survey_id": survey_id,
        **fields,
        "order": order,
        "created_at": now,
        "updated_at": now,
    }

    result = db.questions.insert_one(question)
    question["_id"] = result.inserted_id

    return jsonify({
        "message": "题目添加成功",
        **serialize_question(question),
    }), 201


@questions_bp.post(
    "/<survey_id>/questions/from-library/<library_question_id>"
)
def add_library_question(survey_id, library_question_id):
    """将指定的题库版本复制到草稿问卷中。"""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    survey, error_response = find_owned_draft_survey(survey_id, user_id)
    if error_response:
        return error_response

    library_question, error_response = find_usable_library_question(
        library_question_id, user_id
    )
    if error_response:
        return error_response

    order = get_next_question_order(survey_id)
    now = datetime.now(timezone.utc)

    question = build_question_from_library(
        survey_id=survey_id,
        library_question=library_question,
        order=order,
        now=now,
    )

    result = db.questions.insert_one(question)
    question["_id"] = result.inserted_id

    return jsonify({
        "message": "已从题库添加题目",
        **serialize_question(question),
    }), 201


@questions_bp.get("/<survey_id>/questions")
def list_questions(survey_id):
    """获取当前用户自己创建的问卷中的题目列表。"""
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    if not ObjectId.is_valid(survey_id):
        return jsonify({"error": "问卷 ID 格式不正确"}), 400

    survey = db.surveys.find_one({
        "_id": ObjectId(survey_id),
        "creator_id": user_id,
    })

    if survey is None:
        return jsonify({"error": "问卷不存在或你没有管理权限"}), 404

    cursor = db.questions.find(
        {"survey_id": survey_id}
    ).sort("order", 1)

    questions = [
        serialize_question(question)
        for question in cursor
    ]

    return jsonify({
        "survey_id": survey_id,
        "survey_title": survey.get("title", ""),
        "count": len(questions),
        "questions": questions,
    }), 200


@questions_bp.put("/<survey_id>/questions/<question_id>")
def update_question(survey_id, question_id):
    """修改草稿问卷中的一道题目，不修改题库中的原始版本。"""
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    survey, error_response = find_owned_draft_survey(
        survey_id, user_id
    )
    if error_response:
        return error_response

    if not ObjectId.is_valid(question_id):
        return jsonify({"error": "题目 ID 格式不正确"}), 400

    question = db.questions.find_one({
        "_id": ObjectId(question_id),
        "survey_id": survey_id,
    })

    if question is None:
        return jsonify({"error": "题目不存在"}), 404

    data = request.get_json(silent=True)
    fields, error = validate_question_data(data)

    if error:
        return jsonify({"error": error}), 400

    fields["updated_at"] = datetime.now(timezone.utc)

    # 只更新问卷自己的题目文档，不更新 question_library。
    db.questions.update_one(
        {
            "_id": question["_id"],
            "survey_id": survey_id,
        },
        {"$set": fields},
    )

    updated_question = db.questions.find_one({
        "_id": question["_id"],
        "survey_id": survey_id,
    })

    return jsonify({
        "message": "题目修改成功",
        **serialize_question(updated_question),
    }), 200


@questions_bp.delete("/<survey_id>/questions/<question_id>")
def delete_question(survey_id, question_id):
    """删除草稿问卷中的一道题目，并重新整理题目顺序。"""
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    survey, error_response = find_owned_draft_survey(
        survey_id, user_id
    )
    if error_response:
        return error_response

    if not ObjectId.is_valid(question_id):
        return jsonify({"error": "题目 ID 格式不正确"}), 400

    question = db.questions.find_one({
        "_id": ObjectId(question_id),
        "survey_id": survey_id,
    })

    if question is None:
        return jsonify({"error": "题目不存在"}), 404

    db.questions.delete_one({
        "_id": question["_id"],
        "survey_id": survey_id,
    })

    remaining = list(
        db.questions.find(
            {"survey_id": survey_id}
        ).sort("order", 1)
    )

    # 先改为负数，再重新编号，降低唯一索引冲突风险。
    for item in remaining:
        db.questions.update_one(
            {
                "_id": item["_id"],
                "survey_id": survey_id,
            },
            {"$set": {"order": -item["order"]}},
        )

    now = datetime.now(timezone.utc)

    for index, item in enumerate(remaining, start=1):
        db.questions.update_one(
            {
                "_id": item["_id"],
                "survey_id": survey_id,
            },
            {
                "$set": {
                    "order": index,
                    "updated_at": now,
                }
            },
        )

    return jsonify({
        "message": "题目删除成功",
        "deleted_question_id": question_id,
        "remaining_count": len(remaining),
    }), 200
