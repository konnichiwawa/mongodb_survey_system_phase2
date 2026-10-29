import copy
import math
from collections import Counter
from datetime import datetime, timezone

from bson import ObjectId
from flask import Blueprint, request, jsonify, session

from app.db import db


responses_bp = Blueprint(
    "responses",
    __name__,
    url_prefix="/api/responses",
)


def answer_is_empty(answer):
    """判断答案是否为空。"""
    return (
        answer is None
        or answer == ""
        or (isinstance(answer, list) and len(answer) == 0)
    )


def is_number(value):
    """只接受有限的数字，不接受布尔值。"""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def normalize_question_id(value):
    """将题目 ID 统一转换为字符串，便于关联答案和跳题规则。"""
    if value is None:
        return None

    return str(value)


def normalize_question(question):
    """规范化题目数据，兼容发布快照及历史题目数据。"""
    if not isinstance(question, dict):
        return None

    normalized = copy.deepcopy(question)

    question_id = (
        normalized.get("_id")
        or normalized.get("question_id")
    )

    if question_id is None:
        return None

    normalized["_id"] = normalize_question_id(question_id)

    jump_rules = normalized.get("jump_rules", [])

    if isinstance(jump_rules, list):
        normalized_rules = []

        for rule in jump_rules:
            if not isinstance(rule, dict):
                continue

            normalized_rule = copy.deepcopy(rule)
            target_id = normalized_rule.get("target_question_id")

            if target_id is not None:
                normalized_rule["target_question_id"] = (
                    normalize_question_id(target_id)
                )

            normalized_rules.append(normalized_rule)

        normalized["jump_rules"] = normalized_rules

    return normalized


def answer_is_valid(question, answer):
    """检查单道题答案的类型、必填要求和校验规则。"""
    question_type = question.get("type")
    required = question.get("required", False)
    validation = question.get("validation", {})

    if answer_is_empty(answer):
        if required:
            return False, "此题为必填题，不能留空"
        return True, ""

    if not isinstance(validation, dict):
        validation = {}

    if question_type == "single_choice":
        if not isinstance(answer, str):
            return False, "单选题答案必须是字符串"

        options = question.get("options", [])

        if not isinstance(options, list):
            options = []

        valid_options = {
            option.get("option_id")
            for option in options
            if isinstance(option, dict)
            and isinstance(option.get("option_id"), str)
        }

        if answer not in valid_options:
            return False, "单选题答案不在可选范围内"

    elif question_type == "multiple_choice":
        if not isinstance(answer, list):
            return False, "多选题答案必须是数组"

        options = question.get("options", [])

        if not isinstance(options, list):
            options = []

        valid_options = {
            option.get("option_id")
            for option in options
            if isinstance(option, dict)
            and isinstance(option.get("option_id"), str)
        }

        if any(
            not isinstance(option_id, str)
            or option_id not in valid_options
            for option_id in answer
        ):
            return False, "多选题包含无效选项"

        if len(set(answer)) != len(answer):
            return False, "多选题不能重复选择同一选项"

        count = len(answer)

        min_selections = validation.get("min_selections")
        max_selections = validation.get("max_selections")
        exact_selections = validation.get("exact_selections")

        if (
            min_selections is not None
            and (
                not is_number(min_selections)
                or count < min_selections
            )
        ):
            return False, "多选题的最小选择数量配置无效或未满足"

        if (
            max_selections is not None
            and (
                not is_number(max_selections)
                or count > max_selections
            )
        ):
            return False, "多选题的最大选择数量配置无效或超出限制"

        if (
            exact_selections is not None
            and (
                not is_number(exact_selections)
                or count != exact_selections
            )
        ):
            return False, "多选题的指定选择数量配置无效或未满足"

    elif question_type == "text":
        if not isinstance(answer, str):
            return False, "文本题答案必须是字符串"

        min_length = validation.get("min_length")
        max_length = validation.get("max_length")
        answer_length = len(answer)

        if (
            min_length is not None
            and (
                not is_number(min_length)
                or answer_length < min_length
            )
        ):
            return False, "文本题的最小长度配置无效或未满足"

        if (
            max_length is not None
            and (
                not is_number(max_length)
                or answer_length > max_length
            )
        ):
            return False, "文本题的最大长度配置无效或超出限制"

    elif question_type == "numeric":
        if not is_number(answer):
            return False, "数值题答案必须是有限数字"

        min_value = validation.get("min_value")
        max_value = validation.get("max_value")
        integer = validation.get("integer", False)

        if min_value is not None:
            if not is_number(min_value):
                return False, "数值题的最小值配置无效"

            if answer < min_value:
                return False, f"数值不能小于 {min_value}"

        if max_value is not None:
            if not is_number(max_value):
                return False, "数值题的最大值配置无效"

            if answer > max_value:
                return False, f"数值不能大于 {max_value}"

        if integer and not float(answer).is_integer():
            return False, "此题必须填写整数"

    else:
        return False, "暂不支持此题型"

    return True, ""


def jump_rule_matches(question, answer, rule):
    """判断当前答案是否满足一条跳转规则。"""
    if answer_is_empty(answer):
        return False

    if not isinstance(rule, dict):
        return False

    question_type = question.get("type")

    if question_type == "single_choice":
        return answer == rule.get("option_id")

    if question_type == "multiple_choice":
        return (
            isinstance(answer, list)
            and rule.get("option_id") in answer
        )

    if question_type == "numeric":
        if not is_number(answer):
            return False

        value = rule.get("value")
        operator = rule.get("operator")

        if not is_number(value):
            return False

        comparisons = {
            "eq": answer == value,
            "ne": answer != value,
            "gt": answer > value,
            "gte": answer >= value,
            "lt": answer < value,
            "lte": answer <= value,
        }

        return comparisons.get(operator, False)

    return False


def get_active_question_ids(questions, received_answers):
    """根据答案和跳转规则计算本次答卷中应该作答的题目。"""
    question_ids = [
        str(question["_id"])
        for question in questions
    ]

    question_by_id = {
        str(question["_id"]): question
        for question in questions
    }

    position_by_id = {
        question_id: index
        for index, question_id in enumerate(question_ids)
    }

    active_ids = []
    index = 0

    while index < len(questions):
        question = questions[index]
        question_id = str(question["_id"])
        active_ids.append(question_id)

        answer = received_answers.get(question_id)
        jump_rules = question.get("jump_rules", [])
        target_index = None

        if isinstance(jump_rules, list):
            for rule in jump_rules:
                if not isinstance(rule, dict):
                    continue

                if not jump_rule_matches(question, answer, rule):
                    continue

                target_id = normalize_question_id(
                    rule.get("target_question_id")
                )

                if target_id not in question_by_id:
                    continue

                candidate_index = position_by_id[target_id]

                if candidate_index <= index:
                    continue

                target_index = candidate_index
                break

        if target_index is not None:
            index = target_index
        else:
            index += 1

    return active_ids


def build_question_snapshot(question):
    """复制题目内容和题库来源信息，作为历史答卷快照。"""
    snapshot = {
        "title": copy.deepcopy(question.get("title")),
        "type": copy.deepcopy(question.get("type")),
        "required": copy.deepcopy(question.get("required", False)),
        "options": copy.deepcopy(question.get("options", [])),
        "validation": copy.deepcopy(question.get("validation", {})),
    }

    if "description" in question:
        snapshot["description"] = copy.deepcopy(
            question["description"]
        )

    if "placeholder" in question:
        snapshot["placeholder"] = copy.deepcopy(
            question["placeholder"]
        )

    if "jump_rules" in question:
        snapshot["jump_rules"] = copy.deepcopy(
            question["jump_rules"]
        )

    for field in (
        "library_question_id",
        "question_key",
        "question_version",
        "version",
        "parent_version_id",
    ):
        if field in question:
            value = question[field]

            if field in (
                "library_question_id",
                "parent_version_id",
            ) and value is not None:
                snapshot[field] = str(value)
            else:
                snapshot[field] = copy.deepcopy(value)

    return snapshot


def get_published_questions(survey):
    """读取发布快照，兼容没有快照的旧问卷。"""
    snapshots = survey.get("question_snapshots")

    if isinstance(snapshots, list):
        questions = []

        for index, snapshot in enumerate(snapshots):
            question = normalize_question(snapshot)

            if question is None:
                continue

            question.setdefault("order", index)
            questions.append(question)

        return sorted(
            questions,
            key=lambda question: question.get("order", 0),
        )

    legacy_questions = db.questions.find({
        "survey_id": str(survey["_id"]),
    }).sort("order", 1)

    questions = []

    for question in legacy_questions:
        normalized = normalize_question(question)

        if normalized is not None:
            questions.append(normalized)

    return questions


def find_library_question(question_key):
    """查找题库逻辑题目或其历史版本。"""
    if not isinstance(question_key, str) or not question_key.strip():
        return None

    # question_key 是逻辑题目的跨版本关联标识。
    question = db.question_library.find_one({
        "question_key": question_key,
    })

    if question is not None:
        return question

    # 兼容某些项目将历史版本单独存放的情况。
    return db.question_library.find_one({
        "versions.question_key": question_key,
    })


def user_can_view_question_stats(question, user_id):
    """
    统计数据只允许题目所有者查看。

    共享权限字段结构尚未确认，因此暂不推断共享规则，
    避免将跨问卷答卷数据暴露给未授权用户。
    """
    if question is None or not user_id:
        return False

    owner_id = (
        question.get("owner_id")
        or question.get("user_id")
        or question.get("created_by")
    )

    return owner_id is not None and str(owner_id) == str(user_id)


def build_question_stats(question_key, library_question):
    """聚合所有问卷中 question_key 相同的题目答案。"""
    answer_count = 0
    response_count = 0
    survey_ids = set()
    answers_by_type = Counter()
    numeric_values = []
    text_values = Counter()

    option_counts = Counter()
    option_labels = {}

    # 按历史答卷快照中的 question_key 识别逻辑题目。
    # 仅处理确实保存了该标识的答案，不用题目标题猜测关联关系。
    for response in db.responses.find({}):
        survey_id = str(response.get("survey_id", ""))

        for item in response.get("answers", []):
            if not isinstance(item, dict):
                continue

            snapshot = item.get("question_snapshot", {})

            if not isinstance(snapshot, dict):
                continue

            if snapshot.get("question_key") != question_key:
                continue

            answer = item.get("answer")

            if answer_is_empty(answer):
                continue

            response_count += 1
            answer_count += 1
            survey_ids.add(survey_id)

            question_type = snapshot.get("type")

            if question_type == "single_choice":
                option_counts[answer] += 1

            elif question_type == "multiple_choice":
                if isinstance(answer, list):
                    for option_id in answer:
                        option_counts[option_id] += 1

            elif question_type == "numeric":
                if is_number(answer):
                    numeric_values.append(answer)

            elif question_type == "text":
                if isinstance(answer, str):
                    text_values[answer] += 1

            for option in snapshot.get("options", []):
                if not isinstance(option, dict):
                    continue

                option_id = option.get("option_id")

                if option_id is not None:
                    option_labels[str(option_id)] = option.get(
                        "label",
                        option.get("text", str(option_id)),
                    )

    question_type = library_question.get("type")

    result = {
        "question_key": question_key,
        "title": library_question.get("title"),
        "type": question_type,
        "survey_count": len(survey_ids),
        "response_count": response_count,
        "answer_count": answer_count,
    }

    if question_type in ("single_choice", "multiple_choice"):
        result["options"] = [
            {
                "option_id": option_id,
                "label": option_labels.get(
                    str(option_id),
                    str(option_id),
                ),
                "count": count,
                "percentage": round(
                    count / sum(option_counts.values()) * 100,
                    2,
                ) if sum(option_counts.values()) else 0,
            }
            for option_id, count in sorted(
                option_counts.items(),
                key=lambda item: str(item[0]),
            )
        ]

        result["total_selections"] = sum(option_counts.values())

    elif question_type == "numeric":
        result["numeric"] = {
            "count": len(numeric_values),
            "average": (
                round(sum(numeric_values) / len(numeric_values), 2)
                if numeric_values else None
            ),
            "min": min(numeric_values) if numeric_values else None,
            "max": max(numeric_values) if numeric_values else None,
        }

    elif question_type == "text":
        result["text_answers"] = [
            {"answer": answer, "count": count}
            for answer, count in text_values.most_common(100)
        ]

    return result


@responses_bp.get("/question-stats/<question_key>")
def question_stats(question_key):
    """查看题库逻辑题目在所有问卷中的统计结果。"""
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    library_question = find_library_question(question_key)

    if library_question is None:
        return jsonify({"error": "题库题目不存在"}), 404

    if not user_can_view_question_stats(library_question, user_id):
        return jsonify({"error": "无权查看此题的统计结果"}), 403

    stats = build_question_stats(question_key, library_question)

    return jsonify({"stats": stats}), 200


@responses_bp.post("/<share_code>")
def submit_response(share_code):
    """登录用户通过问卷分享码提交答案。"""
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "请先登录再提交问卷"}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "请求内容必须是 JSON 对象"}), 400

    answers = data.get("answers")

    if not isinstance(answers, list):
        return jsonify({"error": "answers 必须是数组"}), 400

    survey = db.surveys.find_one({
        "share_code": share_code,
        "status": "published",
    })

    if survey is None:
        return jsonify({
            "error": "问卷不存在、尚未发布或已经关闭"
        }), 404

    now = datetime.now(timezone.utc)
    deadline = survey.get("deadline")

    if deadline is not None:
        if not isinstance(deadline, datetime):
            return jsonify({"error": "问卷截止时间数据无效"}), 500

        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)

        if deadline <= now:
            return jsonify({"error": "问卷已超过截止时间"}), 403

    questions = get_published_questions(survey)

    if not questions:
        return jsonify({"error": "问卷没有可用题目"}), 400

    question_by_id = {
        str(question["_id"]): question
        for question in questions
    }

    received_answers = {}

    for item in answers:
        if not isinstance(item, dict):
            return jsonify({
                "error": "每个答案必须是 JSON 对象"
            }), 400

        question_id = item.get("question_id")

        if not isinstance(question_id, str):
            return jsonify({
                "error": "每个答案都必须提供 question_id"
            }), 400

        if question_id not in question_by_id:
            return jsonify({
                "error": "答案包含不属于此问卷的题目"
            }), 400

        if question_id in received_answers:
            return jsonify({
                "error": "同一道题不能重复提交"
            }), 400

        if "answer" not in item:
            return jsonify({
                "error": "每个答案都必须提供 answer 字段"
            }), 400

        received_answers[question_id] = item["answer"]

    active_question_ids = get_active_question_ids(
        questions,
        received_answers,
    )
    active_question_id_set = set(active_question_ids)

    for question_id in received_answers:
        if question_id not in active_question_id_set:
            return jsonify({
                "error": "答案包含根据条件跳转应被跳过的题目",
                "question_id": question_id,
            }), 400

    for question_id in active_question_ids:
        question = question_by_id[question_id]
        answer = received_answers.get(question_id)

        valid, message = answer_is_valid(question, answer)

        if not valid:
            return jsonify({
                "error": message,
                "question_id": question_id,
            }), 400

    stored_answers = []

    for question_id in active_question_ids:
        if question_id not in received_answers:
            continue

        question = question_by_id[question_id]

        stored_answers.append({
            "question_id": question_id,
            "answer": copy.deepcopy(received_answers[question_id]),
            "question_snapshot": build_question_snapshot(question),
        })

    response_document = {
        "survey_id": str(survey["_id"]),
        "respondent_id": (
            None if survey.get("anonymous", False) else user_id
        ),
        "answers": stored_answers,
        "submitted_at": now,
    }

    result = db.responses.insert_one(response_document)

    return jsonify({
        "message": "答卷提交成功",
        "response_id": str(result.inserted_id),
        "survey_id": str(survey["_id"]),
        "submitted_at": now.isoformat(),
    }), 201
