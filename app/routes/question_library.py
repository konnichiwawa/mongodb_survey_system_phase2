
from copy import deepcopy
from datetime import datetime, timezone
import uuid

from bson import ObjectId
from flask import Blueprint, jsonify, request, session
from pymongo.errors import DuplicateKeyError

from app.db import db
from app.routes.questions import validate_question_data


question_library_bp = Blueprint(
    "question_library",
    __name__,
    url_prefix="/api/question-library",
)


def _now():
    return datetime.now(timezone.utc)


def _logged_in_user():
    user_id = session.get("user_id")

    if not user_id or not ObjectId.is_valid(str(user_id)):
        return None

    return db.users.find_one({"_id": ObjectId(str(user_id))})


def _serialize(doc):
    return {
        "library_question_id": str(doc["_id"]),
        "question_key": doc["question_key"],
        "version": doc["version"],
        "parent_version_id": (
            str(doc["parent_version_id"])
            if doc.get("parent_version_id")
            else None
        ),
        "title": doc.get("title", ""),
        "type": doc.get("type", ""),
        "options": deepcopy(doc.get("options", [])),
        "required": doc.get("required", True),
        "validation": deepcopy(doc.get("validation", {})),
        "jump_rules": deepcopy(doc.get("jump_rules", [])),
        "owner_id": doc.get("owner_id"),
        "owner_username": doc.get("owner_username", ""),
        "shared_with": deepcopy(doc.get("shared_with", [])),
        "created_at": (
            doc["created_at"].isoformat()
            if doc.get("created_at")
            else None
        ),
        "updated_at": (
            doc["updated_at"].isoformat()
            if doc.get("updated_at")
            else None
        ),
        "created_by": doc.get("created_by"),
        "restore_from_version_id": (
            str(doc["restore_from_version_id"])
            if doc.get("restore_from_version_id")
            else None
        ),
    }


def _can_use(doc, user_id):
    user_id = str(user_id)
    owner_id = str(doc.get("owner_id", ""))
    shared_with = [str(value) for value in doc.get("shared_with", [])]

    return owner_id == user_id or user_id in shared_with


def _can_edit(doc, user_id):
    return str(doc.get("owner_id", "")) == str(user_id)


def _copy_question_content(source):
    return {
        "title": deepcopy(source.get("title", "")),
        "type": deepcopy(source.get("type", "")),
        "options": deepcopy(source.get("options", [])),
        "required": deepcopy(source.get("required", True)),
        "validation": deepcopy(source.get("validation", {})),
        "jump_rules": deepcopy(source.get("jump_rules", [])),
    }


def _next_version_number(question_key, fallback=0):
    latest = db.question_library.find_one(
        {"question_key": question_key},
        sort=[("version", -1)],
    )

    if latest is not None:
        return latest["version"] + 1

    return fallback + 1


def _insert_new_version(
    source,
    content,
    user_id,
    restore_from_version_id=None,
):
    question_key = source["question_key"]

    for _ in range(10):
        next_version = _next_version_number(
            question_key,
            fallback=source["version"],
        )
        now = _now()

        new_doc = {
            "question_key": question_key,
            "version": next_version,
            "parent_version_id": source["_id"],
            **_copy_question_content(content),
            "owner_id": source["owner_id"],
            "owner_username": source.get("owner_username", ""),
            "shared_with": deepcopy(source.get("shared_with", [])),
            "created_at": now,
            "updated_at": now,
            "created_by": str(user_id),
        }

        if restore_from_version_id is not None:
            new_doc["restore_from_version_id"] = restore_from_version_id

        try:
            result = db.question_library.insert_one(new_doc)
            new_doc["_id"] = result.inserted_id
            return new_doc
        except DuplicateKeyError:
            continue

    return None


def _get_owned_version(library_question_id, user_id):
    if not ObjectId.is_valid(library_question_id):
        return None, (
            jsonify({"error": "题目版本 ID 格式不正确"}),
            400,
        )

    doc = db.question_library.find_one({
        "_id": ObjectId(library_question_id)
    })

    if doc is None:
        return None, (
            jsonify({"error": "题目版本不存在"}),
            404,
        )

    if not _can_edit(doc, user_id):
        return None, (
            jsonify({"error": "只有题目所有者可以执行此操作"}),
            403,
        )

    return doc, None


def _find_survey_question_uses(question_key, user_id):
    versions = list(
        db.question_library.find({"question_key": question_key})
    )

    version_ids = [str(item["_id"]) for item in versions]
    object_ids = [item["_id"] for item in versions]

    clauses = [{"question_key": question_key}]

    if version_ids:
        clauses.append({
            "library_question_id": {"$in": version_ids}
        })
        clauses.append({
            "library_question_id": {"$in": object_ids}
        })

    questions = db.questions.find({"$or": clauses})

    uses = []
    seen = set()
    user_id = str(user_id)

    for question in questions:
        survey_id = question.get("survey_id", "")

        if not isinstance(survey_id, str) or not ObjectId.is_valid(survey_id):
            continue

        survey = db.surveys.find_one({
            "_id": ObjectId(survey_id),
        })

        if survey is None:
            continue

        if str(survey.get("creator_id", "")) != user_id:
            continue

        question_id = str(question["_id"])
        survey_object_id = str(survey["_id"])
        dedupe_key = (survey_object_id, question_id)

        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)

        library_id = question.get("library_question_id")
        version_doc = None

        if library_id is not None and ObjectId.is_valid(str(library_id)):
            version_doc = db.question_library.find_one({
                "_id": ObjectId(str(library_id)),
                "question_key": question_key,
            })

        question_version = question.get("question_version")

        if question_version is None and version_doc is not None:
            question_version = version_doc.get("version")

        uses.append({
            "survey_id": survey_object_id,
            "survey_title": survey.get("title", ""),
            "survey_status": survey.get("status", "draft"),
            "question_id": question_id,
            "question_title": question.get("title", ""),
            "question_version": question_version,
            "library_question_id": (
                str(library_id) if library_id is not None else None
            ),
        })

    uses.sort(
        key=lambda item: (
            item["survey_title"],
            item["question_title"],
        )
    )

    return uses


@question_library_bp.post("")
def create_library_question():
    user = _logged_in_user()

    if user is None:
        return jsonify({"error": "请先登录"}), 401

    fields, error = validate_question_data(request.get_json(silent=True))

    if error:
        return jsonify({"error": error}), 400

    now = _now()
    user_id = str(user["_id"])

    doc = {
        "question_key": uuid.uuid4().hex,
        "version": 1,
        "parent_version_id": None,
        **deepcopy(fields),
        "owner_id": user_id,
        "owner_username": user.get("username", ""),
        "shared_with": [],
        "created_at": now,
        "updated_at": now,
        "created_by": user_id,
    }

    result = db.question_library.insert_one(doc)
    doc["_id"] = result.inserted_id

    return jsonify({
        "message": "题目已保存到题库",
        "question": _serialize(doc),
    }), 201


@question_library_bp.get("")
def list_library_questions():
    user = _logged_in_user()

    if user is None:
        return jsonify({"error": "请先登录"}), 401

    user_id = str(user["_id"])

    docs = list(
        db.question_library.find({
            "$or": [
                {"owner_id": user_id},
                {"shared_with": user_id},
            ]
        }).sort([
            ("question_key", 1),
            ("version", -1),
        ])
    )

    # Also support documents where shared_with contains non-string IDs.
    docs = [
        doc for doc in docs
        if _can_use(doc, user_id)
    ]

    return jsonify({
        "count": len(docs),
        "questions": [_serialize(doc) for doc in docs],
    }), 200


@question_library_bp.get("/<question_key>/history")
def question_history(question_key):
    user = _logged_in_user()

    if user is None:
        return jsonify({"error": "请先登录"}), 401

    user_id = str(user["_id"])

    versions = list(
        db.question_library.find({
            "question_key": question_key
        }).sort("version", 1)
    )

    visible = [
        doc for doc in versions if _can_use(doc, user_id)
    ]

    if not visible:
        return jsonify({
            "error": "题目不存在或你没有查看权限"
        }), 404

    return jsonify({
        "question_key": question_key,
        "versions": [_serialize(doc) for doc in visible],
    }), 200


@question_library_bp.post("/<library_question_id>/versions")
def create_question_version(library_question_id):
    user = _logged_in_user()

    if user is None:
        return jsonify({"error": "请先登录"}), 401

    user_id = str(user["_id"])

    source, error_response = _get_owned_version(
        library_question_id,
        user_id,
    )

    if error_response is not None:
        return error_response

    fields, error = validate_question_data(request.get_json(silent=True))

    if error:
        return jsonify({"error": error}), 400

    new_doc = _insert_new_version(
        source=source,
        content=fields,
        user_id=user_id,
    )

    if new_doc is None:
        return jsonify({
            "error": "创建版本时发生冲突，请重试"
        }), 409

    return jsonify({
        "message": "新版本创建成功，旧版本未被修改",
        "question": _serialize(new_doc),
    }), 201


@question_library_bp.post("/<library_question_id>/edit")
def edit_library_question(library_question_id):
    user = _logged_in_user()

    if user is None:
        return jsonify({"error": "请先登录"}), 401

    user_id = str(user["_id"])

    source, error_response = _get_owned_version(
        library_question_id,
        user_id,
    )

    if error_response is not None:
        return error_response

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "请求内容必须是 JSON 对象"}), 400

    if data.get("create_new_version") is not True:
        return jsonify({
            "error": (
                "题库历史版本不可直接覆盖。"
                "如需修改题目，请将 create_new_version 设置为 true。"
            )
        }), 400

    fields, error = validate_question_data(data)

    if error:
        return jsonify({"error": error}), 400

    new_doc = _insert_new_version(
        source=source,
        content=fields,
        user_id=user_id,
    )

    if new_doc is None:
        return jsonify({
            "error": "创建版本时发生冲突，请重试"
        }), 409

    uses = _find_survey_question_uses(
        source["question_key"],
        user_id,
    )

    return jsonify({
        "message": "修改已保存为新版本，历史版本及问卷中的题目不会被覆盖",
        "question": _serialize(new_doc),
        "uses": uses,
        "uses_count": len(uses),
    }), 201


@question_library_bp.post("/<library_question_id>/restore")
def restore_question_version(library_question_id):
    user = _logged_in_user()

    if user is None:
        return jsonify({"error": "请先登录"}), 401

    user_id = str(user["_id"])

    current_source, error_response = _get_owned_version(
        library_question_id,
        user_id,
    )

    if error_response is not None:
        return error_response

    data = request.get_json(silent=True)

    target_version_id = (
        data.get("target_version_id")
        if isinstance(data, dict)
        else None
    )

    if (
        not isinstance(target_version_id, str)
        or not ObjectId.is_valid(target_version_id)
    ):
        return jsonify({
            "error": "请提供有效的 target_version_id"
        }), 400

    target = db.question_library.find_one({
        "_id": ObjectId(target_version_id)
    })

    if target is None:
        return jsonify({
            "error": "要恢复的历史版本不存在"
        }), 404

    if target.get("question_key") != current_source.get("question_key"):
        return jsonify({
            "error": "只能恢复同一道题的历史版本"
        }), 400

    if not _can_edit(target, user_id):
        return jsonify({
            "error": "只有题目所有者可以恢复该历史版本"
        }), 403

    new_doc = _insert_new_version(
        source=target,
        content=_copy_question_content(target),
        user_id=user_id,
        restore_from_version_id=target["_id"],
    )

    if new_doc is None:
        return jsonify({
            "error": "恢复版本时发生冲突，请重试"
        }), 409

    return jsonify({
        "message": (
            f"已恢复历史版本 v{target['version']}，"
            f"并创建新版本 v{new_doc['version']}"
        ),
        "question": _serialize(new_doc),
    }), 201


@question_library_bp.post("/<library_question_id>/share")
def share_library_question(library_question_id):
    user = _logged_in_user()

    if user is None:
        return jsonify({"error": "请先登录"}), 401

    doc, error_response = _get_owned_version(
        library_question_id,
        str(user["_id"]),
    )

    if error_response is not None:
        return error_response

    data = request.get_json(silent=True)

    username = data.get("username") if isinstance(data, dict) else None

    if not isinstance(username, str) or not username.strip():
        return jsonify({"error": "请提供要共享的用户名"}), 400

    target = db.users.find_one({
        "username": username.strip()
    })

    if target is None:
        return jsonify({"error": "目标用户不存在"}), 404

    target_id = str(target["_id"])

    if target_id == str(doc["owner_id"]):
        return jsonify({"error": "无需向自己共享"}), 400

    db.question_library.update_one(
        {"_id": doc["_id"]},
        {
            "$addToSet": {"shared_with": target_id},
            "$set": {"updated_at": _now()},
        },
    )

    return jsonify({
        "message": "题目共享成功",
        "shared_with_username": target["username"],
    }), 200


@question_library_bp.get("/<library_question_id>/uses")
def question_uses(library_question_id):
    user = _logged_in_user()

    if user is None:
        return jsonify({"error": "请先登录"}), 401

    if not ObjectId.is_valid(library_question_id):
        return jsonify({"error": "题目版本 ID 格式不正确"}), 400

    doc = db.question_library.find_one({
        "_id": ObjectId(library_question_id)
    })

    if doc is None or not _can_use(doc, str(user["_id"])):
        return jsonify({
            "error": "题目不存在或你没有查看权限"
        }), 404

    uses = _find_survey_question_uses(
        doc["question_key"],
        str(user["_id"]),
    )

    return jsonify({
        "question_key": doc["question_key"],
        "version": doc["version"],
        "count": len(uses),
        "uses": uses,
    }), 200
