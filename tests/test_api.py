
import os
import uuid

import pytest

# 必须在导入应用代码前指定测试数据库。
os.environ["MONGO_DB_NAME"] = "survey_system_test"
os.environ["SECRET_KEY"] = "pytest-test-secret-key"

from app import create_app
from app.db import db
from app.init_db import create_collections, create_indexes


@pytest.fixture
def client():
    """每个测试前清理独立测试库，并创建 Flask 测试客户端。"""
    create_collections()
    create_indexes()

    for name in (
        "users", "surveys", "questions", "responses", "question_library"
    ):
        db[name].delete_many({})

    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "pytest-test-secret-key"

    with app.test_client() as test_client:
        yield test_client

    for name in (
        "users", "surveys", "questions", "responses", "question_library"
    ):
        db[name].delete_many({})


def register_and_login(client):
    """注册唯一测试用户并登录。"""
    username = "pytest_" + uuid.uuid4().hex[:12]
    password = "TestPass123!"

    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert response.status_code == 201, response.get_json()

    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.get_json()

    return username


def create_survey(client, title="自动化测试问卷"):
    response = client.post(
        "/api/surveys",
        json={
            "title": title,
            "description": "pytest 自动化测试",
            "anonymous": False,
        },
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def add_question(client, survey_id, payload):
    return client.post(
        f"/api/surveys/{survey_id}/questions",
        json=payload,
    )


def publish_survey(client, survey_id):
    response = client.post(f"/api/surveys/{survey_id}/publish")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def create_age_library_question(client, title="你的年龄"):
    """创建并保存一个年龄题目，供题库测试复用。"""
    response = client.post(
        "/api/question-library",
        json={
            "title": title,
            "type": "numeric",
            "required": True,
            "validation": {
                "min_value": 0,
                "max_value": 120,
                "integer": True,
            },
        },
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["question"]


def add_library_question(client, survey_id, library_question_id):
    """把题库题目添加到指定问卷。"""
    return client.post(
        f"/api/surveys/{survey_id}/questions/from-library/{library_question_id}"
    )


def create_age_version(client, library_question_id, title):
    """基于指定题库版本创建新版本。"""
    return client.post(
        f"/api/question-library/{library_question_id}/versions",
        json={
            "title": title,
            "type": "numeric",
            "required": True,
            "validation": {
                "min_value": 0,
                "max_value": 120,
                "integer": True,
            },
        },
    )


def test_health_endpoint():
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as test_client:
        response = test_client.get("/health")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_register_login_and_current_user(client):
    username = register_and_login(client)

    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.get_json()["logged_in"] is True
    assert response.get_json()["username"] == username

    response = client.post("/api/auth/logout")
    assert response.status_code == 200

    response = client.get("/api/auth/me")
    assert response.get_json()["logged_in"] is False


def test_duplicate_registration_is_rejected(client):
    username = "duplicate_" + uuid.uuid4().hex[:10]
    payload = {"username": username, "password": "TestPass123!"}

    first = client.post("/api/auth/register", json=payload)
    second = client.post("/api/auth/register", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409


def test_survey_requires_login(client):
    response = client.post(
        "/api/surveys",
        json={"title": "未登录问卷"},
    )
    assert response.status_code == 401


def test_create_question_publish_and_access_share_link(client):
    register_and_login(client)
    survey = create_survey(client)
    survey_id = survey["survey_id"]

    question_response = add_question(
        client,
        survey_id,
        {
            "title": "你最喜欢哪种数据库？",
            "type": "single_choice",
            "required": True,
            "options": ["MongoDB", "MySQL"],
        },
    )
    assert question_response.status_code == 201
    question = question_response.get_json()
    assert question["options"][0]["option_id"] == "1"

    published = publish_survey(client, survey_id)
    assert published["status"] == "published"

    share_code = published["share_code"]
    public_response = client.get(f"/api/surveys/share/{share_code}")

    assert public_response.status_code == 200
    assert public_response.get_json()["title"] == survey["title"]
    assert len(public_response.get_json()["questions"]) == 1


def test_question_validation_rejects_duplicate_options(client):
    register_and_login(client)
    survey = create_survey(client)

    response = add_question(
        client,
        survey["survey_id"],
        {
            "title": "重复选项测试",
            "type": "single_choice",
            "options": ["相同", "相同"],
        },
    )

    assert response.status_code == 400
    assert "不能重复" in response.get_json()["error"]


def test_submission_and_statistics(client):
    register_and_login(client)
    survey = create_survey(client, "答卷统计测试")

    question_specs = [
        {
            "title": "选择数据库",
            "type": "single_choice",
            "required": True,
            "options": ["MongoDB", "MySQL"],
        },
        {
            "title": "使用过哪些数据库",
            "type": "multiple_choice",
            "required": True,
            "options": ["MongoDB", "MySQL", "PostgreSQL"],
            "validation": {"min_selections": 1, "max_selections": 2},
        },
        {
            "title": "使用感受",
            "type": "text",
            "required": True,
            "validation": {"min_length": 2, "max_length": 100},
        },
        {
            "title": "打分",
            "type": "numeric",
            "required": True,
            "validation": {
                "min_value": 1,
                "max_value": 10,
                "integer": True,
            },
        },
    ]

    question_ids = []
    for spec in question_specs:
        response = add_question(client, survey["survey_id"], spec)
        assert response.status_code == 201, response.get_json()
        question_ids.append(response.get_json()["question_id"])

    published = publish_survey(client, survey["survey_id"])
    share_code = published["share_code"]

    submission = client.post(
        f"/api/responses/{share_code}",
        json={
            "answers": [
                {"question_id": question_ids[0], "answer": "1"},
                {"question_id": question_ids[1], "answer": ["1", "2"]},
                {"question_id": question_ids[2], "answer": "使用起来比较灵活"},
                {"question_id": question_ids[3], "answer": 8},
            ]
        },
    )
    assert submission.status_code == 201, submission.get_json()

    stats_response = client.get(
        f"/api/surveys/{survey['survey_id']}/stats"
    )
    assert stats_response.status_code == 200

    stats = stats_response.get_json()
    assert stats["response_count"] == 1
    assert stats["questions"][0]["options"][0]["count"] == 1
    assert stats["questions"][1]["options"][0]["count"] == 1
    assert stats["questions"][2]["answers"] == ["使用起来比较灵活"]
    assert stats["questions"][3]["average"] == 8


def test_invalid_answers_are_rejected(client):
    register_and_login(client)
    survey = create_survey(client, "答案校验测试")

    question_response = add_question(
        client,
        survey["survey_id"],
        {
            "title": "1 到 10 的整数",
            "type": "numeric",
            "required": True,
            "validation": {
                "min_value": 1,
                "max_value": 10,
                "integer": True,
            },
        },
    )
    assert question_response.status_code == 201
    question_id = question_response.get_json()["question_id"]

    published = publish_survey(client, survey["survey_id"])

    response = client.post(
        f"/api/responses/{published['share_code']}",
        json={"answers": [{"question_id": question_id, "answer": 11}]},
    )

    assert response.status_code == 400
    assert "不能大于 10" in response.get_json()["error"]


def test_single_choice_jump_skips_intermediate_question(client):
    register_and_login(client)
    survey = create_survey(client, "条件跳转测试")
    survey_id = survey["survey_id"]

    first = add_question(
        client,
        survey_id,
        {
            "title": "是否使用过 MongoDB？",
            "type": "single_choice",
            "required": True,
            "options": ["使用过", "没使用过"],
        },
    )
    assert first.status_code == 201, first.get_json()
    first_id = first.get_json()["question_id"]

    second = add_question(
        client,
        survey_id,
        {"title": "中间题", "type": "text", "required": True},
    )
    assert second.status_code == 201, second.get_json()
    second_id = second.get_json()["question_id"]

    third = add_question(
        client,
        survey_id,
        {"title": "跳转目标题", "type": "text", "required": True},
    )
    assert third.status_code == 201, third.get_json()
    third_id = third.get_json()["question_id"]

    update = client.put(
        f"/api/surveys/{survey_id}/questions/{first_id}",
        json={
            "title": "是否使用过 MongoDB？",
            "type": "single_choice",
            "required": True,
            "options": ["使用过", "没使用过"],
            "jump_rules": [{"option_id": "1", "target_question_id": third_id}],
        },
    )
    assert update.status_code == 200, update.get_json()

    published = publish_survey(client, survey_id)
    share_code = published["share_code"]

    valid_submission = client.post(
        f"/api/responses/{share_code}",
        json={
            "answers": [
                {"question_id": first_id, "answer": "1"},
                {"question_id": third_id, "answer": "目标回答"},
            ]
        },
    )
    assert valid_submission.status_code == 201, valid_submission.get_json()

    invalid_submission = client.post(
        f"/api/responses/{share_code}",
        json={
            "answers": [
                {"question_id": first_id, "answer": "1"},
                {"question_id": second_id, "answer": "不应填写"},
                {"question_id": third_id, "answer": "目标回答"},
            ]
        },
    )
    assert invalid_submission.status_code == 400
    assert "应被跳过" in invalid_submission.get_json()["error"]


def test_question_library_create_and_list(client):
    register_and_login(client)

    created = client.post(
        "/api/question-library",
        json={
            "title": "你的年龄",
            "type": "numeric",
            "required": True,
            "validation": {
                "min_value": 0,
                "max_value": 120,
                "integer": True,
            },
        },
    )
    assert created.status_code == 201
    assert created.get_json()["question"]["version"] == 1

    listed = client.get("/api/question-library")
    assert listed.status_code == 200
    assert listed.get_json()["count"] == 1


def test_question_library_version_is_immutable_and_linked(client):
    register_and_login(client)
    first = create_age_library_question(client)

    second_response = create_age_version(
        client,
        first["library_question_id"],
        "你的年龄（周岁）",
    )
    assert second_response.status_code == 201, second_response.get_json()

    second = second_response.get_json()["question"]
    assert second["version"] == 2
    assert second["parent_version_id"] == first["library_question_id"]

    history = client.get(
        f"/api/question-library/{first['question_key']}/history"
    )
    assert history.status_code == 200
    assert [q["version"] for q in history.get_json()["versions"]] == [1, 2]


def test_library_question_can_be_added_to_draft_survey(client):
    register_and_login(client)
    library_question = create_age_library_question(client)
    survey = create_survey(client, "题库选题测试")

    attached = add_library_question(
        client, survey["survey_id"], library_question["library_question_id"]
    )

    assert attached.status_code == 201, attached.get_json()
    question = attached.get_json()
    assert question["title"] == "你的年龄"
    assert question["question_version"] == 1
    assert question["library_question_id"] == library_question["library_question_id"]


def test_library_question_can_be_reused_in_two_surveys(client):
    """同一道题可以被两份问卷重复使用。"""
    register_and_login(client)
    library_question = create_age_library_question(client)
    library_id = library_question["library_question_id"]

    survey1 = create_survey(client, "复用测试问卷一")
    survey2 = create_survey(client, "复用测试问卷二")

    attached1 = add_library_question(client, survey1["survey_id"], library_id)
    attached2 = add_library_question(client, survey2["survey_id"], library_id)

    assert attached1.status_code == 201, attached1.get_json()
    assert attached2.status_code == 201, attached2.get_json()
    assert attached1.get_json()["question_version"] == 1
    assert attached2.get_json()["question_version"] == 1


def test_reused_question_is_independent_between_surveys(client):
    """修改一份问卷中的复用题目，不应影响另一份问卷。"""
    register_and_login(client)
    library_question = create_age_library_question(client)
    library_id = library_question["library_question_id"]

    survey1 = create_survey(client, "独立性测试问卷一")
    survey2 = create_survey(client, "独立性测试问卷二")

    attached1 = add_library_question(client, survey1["survey_id"], library_id)
    attached2 = add_library_question(client, survey2["survey_id"], library_id)

    assert attached1.status_code == 201, attached1.get_json()
    assert attached2.status_code == 201, attached2.get_json()

    question1 = attached1.get_json()
    updated = client.put(
        f"/api/surveys/{survey1['survey_id']}/questions/{question1['question_id']}",
        json={
            "title": "修改后的年龄问题",
            "type": "numeric",
            "required": True,
            "validation": {
                "min_value": 1,
                "max_value": 100,
                "integer": True,
            },
        },
    )
    assert updated.status_code == 200, updated.get_json()

    questions2_response = client.get(
        f"/api/surveys/{survey2['survey_id']}/questions"
    )
    assert questions2_response.status_code == 200
    titles2 = [
        q["title"] for q in questions2_response.get_json()["questions"]
    ]
    assert "你的年龄" in titles2
    assert "修改后的年龄问题" not in titles2


def test_private_library_question_cannot_be_used_by_another_user(client):
    """其他用户不能使用未分享给自己的私有题目。"""
    register_and_login(client)
    response = client.post(
        "/api/question-library",
        json={"title": "私有题目", "type": "text", "required": True},
    )
    assert response.status_code == 201, response.get_json()
    library_id = response.get_json()["question"]["library_question_id"]

    client.post("/api/auth/logout")
    register_and_login(client)
    survey = create_survey(client, "权限测试问卷")

    denied = add_library_question(client, survey["survey_id"], library_id)
    assert denied.status_code in (403, 404), denied.get_json()


def test_shared_library_question_can_be_used_by_another_user(client):
    """题目分享给其他用户后，对方可以在自己的问卷中使用。"""
    teacher = register_and_login(client)
    library = create_age_library_question(client)
    library_id = library["library_question_id"]

    client.post("/api/auth/logout")
    student = register_and_login(client)
    student_survey = create_survey(client, "学生分享权限测试")

    denied = add_library_question(client, student_survey["survey_id"], library_id)
    assert denied.status_code in (403, 404), denied.get_json()

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"username": teacher, "password": "TestPass123!"},
    )
    assert login.status_code == 200, login.get_json()

    share = client.post(
        f"/api/question-library/{library_id}/share",
        json={"username": student},
    )
    assert share.status_code == 200, share.get_json()

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"username": student, "password": "TestPass123!"},
    )
    assert login.status_code == 200, login.get_json()

    allowed = add_library_question(client, student_survey["survey_id"], library_id)
    assert allowed.status_code == 201, allowed.get_json()
    assert allowed.get_json()["title"] == "你的年龄"

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"username": teacher, "password": "TestPass123!"},
    )
    assert login.status_code == 200

    listed = client.get("/api/question-library")
    assert listed.status_code == 200
    assert any(
        q["library_question_id"] == library_id
        for q in listed.get_json()["questions"]
    )


def test_shared_question_can_be_reused_and_remains_independent(client):
    """学生可重复使用共享题目，修改自己的问卷不影响题库原题。"""
    teacher = register_and_login(client)
    library = create_age_library_question(client)
    library_id = library["library_question_id"]

    client.post("/api/auth/logout")
    student = register_and_login(client)

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"username": teacher, "password": "TestPass123!"},
    )
    assert login.status_code == 200

    shared = client.post(
        f"/api/question-library/{library_id}/share",
        json={"username": student},
    )
    assert shared.status_code == 200, shared.get_json()

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"username": student, "password": "TestPass123!"},
    )
    assert login.status_code == 200

    survey1 = create_survey(client, "共享复用问卷一")
    survey2 = create_survey(client, "共享复用问卷二")

    first = add_library_question(client, survey1["survey_id"], library_id)
    second = add_library_question(client, survey2["survey_id"], library_id)
    assert first.status_code == 201, first.get_json()
    assert second.status_code == 201, second.get_json()

    update = client.put(
        f"/api/surveys/{survey1['survey_id']}/questions/{first.get_json()['question_id']}",
        json={
            "title": "学生自己的修改",
            "type": "numeric",
            "required": True,
            "validation": {
                "min_value": 1,
                "max_value": 100,
                "integer": True,
            },
        },
    )
    assert update.status_code == 200, update.get_json()

    other_questions = client.get(
        f"/api/surveys/{survey2['survey_id']}/questions"
    )
    assert other_questions.status_code == 200
    assert "你的年龄" in [
        q["title"] for q in other_questions.get_json()["questions"]
    ]

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"username": teacher, "password": "TestPass123!"},
    )
    assert login.status_code == 200

    history = client.get(
        f"/api/question-library/{library['question_key']}/history"
    )
    assert history.status_code == 200
    assert history.get_json()["versions"][0]["title"] == "你的年龄"


def test_shared_question_is_not_accessible_to_third_user(client):
    """分享给学生后，未获分享的第三个用户仍不能使用该题。"""
    teacher = register_and_login(client)
    library = create_age_library_question(client)
    library_id = library["library_question_id"]

    client.post("/api/auth/logout")
    student = register_and_login(client)

    client.post("/api/auth/logout")
    third_user = register_and_login(client)
    third_survey = create_survey(client, "第三用户权限测试")

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"username": teacher, "password": "TestPass123!"},
    )
    assert login.status_code == 200

    share = client.post(
        f"/api/question-library/{library_id}/share",
        json={"username": student},
    )
    assert share.status_code == 200, share.get_json()

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"username": third_user, "password": "TestPass123!"},
    )
    assert login.status_code == 200

    denied = add_library_question(client, third_survey["survey_id"], library_id)
    assert denied.status_code in (403, 404), denied.get_json()


def test_sharing_with_nonexistent_user_is_rejected(client):
    """分享给不存在的用户名应被拒绝。"""
    register_and_login(client)
    library = create_age_library_question(client)

    response = client.post(
        f"/api/question-library/{library['library_question_id']}/share",
        json={"username": "missing_" + uuid.uuid4().hex[:12]},
    )
    assert response.status_code in (400, 404), response.get_json()


def test_non_owner_cannot_share_library_question(client):
    """非题目所有者不能擅自转分享题目。"""
    owner = register_and_login(client)
    library = create_age_library_question(client)

    client.post("/api/auth/logout")
    register_and_login(client)

    response = client.post(
        f"/api/question-library/{library['library_question_id']}/share",
        json={"username": owner},
    )
    assert response.status_code in (403, 404), response.get_json()


def test_sharing_same_question_twice_does_not_duplicate_permission(client):
    """重复分享同一道题，不应产生重复授权记录，且使用权限保持有效。"""
    teacher = register_and_login(client)
    library = create_age_library_question(client)
    library_id = library["library_question_id"]

    client.post("/api/auth/logout")
    student = register_and_login(client)

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"username": teacher, "password": "TestPass123!"},
    )
    assert login.status_code == 200

    first_share = client.post(
        f"/api/question-library/{library_id}/share",
        json={"username": student},
    )
    assert first_share.status_code == 200, first_share.get_json()

    second_share = client.post(
        f"/api/question-library/{library_id}/share",
        json={"username": student},
    )
    assert second_share.status_code == 200, second_share.get_json()

    library_doc = db.question_library.find_one({
        "question_key": library["question_key"],
        "version": 1,
    })
    assert library_doc is not None

    student_doc = db.users.find_one({"username": student})
    assert student_doc is not None

    shared_with = library_doc.get("shared_with", [])
    student_id = student_doc["_id"]
    assert sum(
        1 for item in shared_with if str(item) == str(student_id)
    ) == 1

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"username": student, "password": "TestPass123!"},
    )
    assert login.status_code == 200

    survey = create_survey(client, "重复分享后使用测试")
    used = add_library_question(client, survey["survey_id"], library_id)
    assert used.status_code == 201, used.get_json()


# -------------------- 任务三：版本和问卷保护测试 --------------------


def test_creating_new_library_version_does_not_change_old_version(client):
    """创建新版本后，数据库中的旧版本内容保持不变。"""
    register_and_login(client)
    first = create_age_library_question(client, "原始年龄题")

    old_before = db.question_library.find_one({
        "_id": __import__("bson").ObjectId(first["library_question_id"])
    })
    assert old_before is not None

    response = create_age_version(
        client,
        first["library_question_id"],
        "修改后的年龄题",
    )
    assert response.status_code == 201, response.get_json()

    old_after = db.question_library.find_one({
        "_id": __import__("bson").ObjectId(first["library_question_id"])
    })
    assert old_after is not None
    assert old_after["version"] == 1
    assert old_after["title"] == old_before["title"]
    assert old_after["validation"] == old_before["validation"]

    new_doc = response.get_json()["question"]
    assert new_doc["version"] == 2
    assert new_doc["title"] == "修改后的年龄题"


def test_new_library_version_does_not_change_existing_survey_snapshot(client):
    """已加入问卷的题目应保持原快照，不自动跟随题库更新。"""
    register_and_login(client)
    first = create_age_library_question(client, "旧问卷年龄题")
    survey = create_survey(client, "旧版本快照测试")

    attached = add_library_question(
        client, survey["survey_id"], first["library_question_id"]
    )
    assert attached.status_code == 201, attached.get_json()
    question_id = attached.get_json()["question_id"]

    new_version = create_age_version(
        client,
        first["library_question_id"],
        "新版本年龄题",
    )
    assert new_version.status_code == 201, new_version.get_json()

    questions_response = client.get(
        f"/api/surveys/{survey['survey_id']}/questions"
    )
    assert questions_response.status_code == 200

    questions = questions_response.get_json()["questions"]
    snapshot = next(q for q in questions if q["question_id"] == question_id)

    assert snapshot["title"] == "旧问卷年龄题"
    assert snapshot["question_version"] == 1


def test_published_survey_question_cannot_be_updated_or_deleted(client):
    """已发布问卷的题目不能通过 API 修改或删除。"""
    register_and_login(client)
    survey = create_survey(client, "已发布题目保护测试")

    created = add_question(
        client,
        survey["survey_id"],
        {
            "title": "已发布的题目",
            "type": "text",
            "required": True,
        },
    )
    assert created.status_code == 201, created.get_json()
    question_id = created.get_json()["question_id"]

    publish_survey(client, survey["survey_id"])

    update = client.put(
        f"/api/surveys/{survey['survey_id']}/questions/{question_id}",
        json={
            "title": "试图修改的题目",
            "type": "text",
            "required": True,
        },
    )
    assert update.status_code == 400, update.get_json()

    delete = client.delete(
        f"/api/surveys/{survey['survey_id']}/questions/{question_id}"
    )
    assert delete.status_code == 400, delete.get_json()

    # 再读取题目，确认内容仍然未改变。
    questions_response = client.get(
        f"/api/surveys/{survey['survey_id']}/questions"
    )
    assert questions_response.status_code == 200

    questions = questions_response.get_json()["questions"]
    saved_question = next(
        q for q in questions if q["question_id"] == question_id
    )
    assert saved_question["title"] == "已发布的题目"



def test_historical_response_is_preserved_after_new_library_version(client):
    """创建新题库版本后，历史答卷的答案和题目快照均保持不变。"""
    register_and_login(client)

    first = client.post(
        "/api/question-library",
        json={
            "title": "答卷中的原始年龄题",
            "type": "numeric",
            "required": True,
            "validation": {
                "min_value": 0,
                "max_value": 120,
                "integer": True,
            },
        },
    )
    assert first.status_code == 201, first.get_json()
    library_question = first.get_json()["question"]

    survey = create_survey(client, "历史答卷保护测试")

    attached = add_library_question(
        client,
        survey["survey_id"],
        library_question["library_question_id"],
    )
    assert attached.status_code == 201, attached.get_json()

    question_id = attached.get_json()["question_id"]

    # 修改问卷题目为带选项的题目并非必要；
    # 年龄题本身即可验证标题、题型和校验规则的快照。
    published = publish_survey(client, survey["survey_id"])
    share_code = published["share_code"]

    submitted = client.post(
        f"/api/responses/{share_code}",
        json={
            "answers": [
                {"question_id": question_id, "answer": 25}
            ]
        },
    )
    assert submitted.status_code == 201, submitted.get_json()

    response_id = submitted.get_json()["response_id"]

    # 按提交接口返回的答卷 ID 读取，避免误读其他答卷。
    from bson import ObjectId

    response_doc_before = db.responses.find_one({
        "_id": ObjectId(response_id)
    })
    assert response_doc_before is not None
    assert len(response_doc_before["answers"]) == 1

    stored_answer_before = response_doc_before["answers"][0]
    snapshot_before = stored_answer_before.get("question_snapshot")

    assert snapshot_before is not None
    assert snapshot_before["title"] == "答卷中的原始年龄题"
    assert snapshot_before["type"] == "numeric"
    assert snapshot_before["required"] is True
    assert snapshot_before["validation"] == {
        "min_value": 0,
        "max_value": 120,
        "integer": True,
    }
    assert stored_answer_before["answer"] == 25

    # 基于题库原题创建新版本。
    new_version = client.post(
        f"/api/question-library/{library_question['library_question_id']}/versions",
        json={
            "title": "答卷提交后的新题目版本",
            "type": "numeric",
            "required": True,
            "validation": {
                "min_value": 18,
                "max_value": 99,
                "integer": True,
            },
        },
    )
    assert new_version.status_code == 201, new_version.get_json()

    # 历史答卷里的题目快照与答案都应保持不变。
    response_doc_after = db.responses.find_one({
        "_id": ObjectId(response_id)
    })
    assert response_doc_after is not None

    stored_answer_after = response_doc_after["answers"][0]

    assert stored_answer_after["answer"] == 25
    assert stored_answer_after["question_snapshot"] == snapshot_before
    assert stored_answer_after["question_snapshot"]["title"] == "答卷中的原始年龄题"
    assert stored_answer_after["question_snapshot"]["validation"]["min_value"] == 0
    assert response_doc_after["survey_id"] == survey["survey_id"]


# -------------------- 任务四：题目历史与恢复测试 --------------------


def test_question_history_records_version_parent_relationship(client):
    """v1 -> v2 -> v3 能查询，且每个版本记录来源版本。"""
    register_and_login(client)
    v1 = create_age_library_question(client, "年龄题 v1")

    v2_response = create_age_version(
        client, v1["library_question_id"], "年龄题 v2"
    )
    assert v2_response.status_code == 201, v2_response.get_json()
    v2 = v2_response.get_json()["question"]

    v3_response = create_age_version(
        client, v2["library_question_id"], "年龄题 v3"
    )
    assert v3_response.status_code == 201, v3_response.get_json()
    v3 = v3_response.get_json()["question"]

    assert v2["parent_version_id"] == v1["library_question_id"]
    assert v3["parent_version_id"] == v2["library_question_id"]

    history_response = client.get(
        f"/api/question-library/{v1['question_key']}/history"
    )
    assert history_response.status_code == 200

    versions = history_response.get_json()["versions"]
    assert [item["version"] for item in versions] == [1, 2, 3]
    assert [item["title"] for item in versions] == [
        "年龄题 v1", "年龄题 v2", "年龄题 v3"
    ]
    assert versions[0]["parent_version_id"] is None
    assert versions[1]["parent_version_id"] == v1["library_question_id"]
    assert versions[2]["parent_version_id"] == v2["library_question_id"]


def test_restore_old_version_creates_new_version_without_overwriting_history(client):
    """恢复 v1 应生成 v3，保留 v1、v2，并明确记录恢复来源。"""
    register_and_login(client)
    v1 = create_age_library_question(client, "原始年龄题 v1")

    v2_response = create_age_version(
        client, v1["library_question_id"], "修改后的年龄题 v2"
    )
    assert v2_response.status_code == 201, v2_response.get_json()
    v2 = v2_response.get_json()["question"]

    restore_response = client.post(
        f"/api/question-library/{v2['library_question_id']}/restore",
        json={"target_version_id": v1["library_question_id"]},
    )
    assert restore_response.status_code == 201, restore_response.get_json()

    v3 = restore_response.get_json()["question"]
    assert v3["version"] == 3
    assert v3["title"] == v1["title"]
    assert v3["type"] == v1["type"]
    assert v3["options"] == v1["options"]
    assert v3["required"] == v1["required"]
    assert v3["validation"] == v1["validation"]

    # 来源关系和恢复来源均明确指向被恢复的 v1。
    assert v3["parent_version_id"] == v1["library_question_id"]
    assert v3["restore_from_version_id"] == v1["library_question_id"]

    # v1 和 v2 都没有被覆盖。
    old_v1 = db.question_library.find_one({
        "_id": __import__("bson").ObjectId(v1["library_question_id"])
    })
    old_v2 = db.question_library.find_one({
        "_id": __import__("bson").ObjectId(v2["library_question_id"])
    })
    assert old_v1["title"] == "原始年龄题 v1"
    assert old_v2["title"] == "修改后的年龄题 v2"

    history = client.get(
        f"/api/question-library/{v1['question_key']}/history"
    )
    assert history.status_code == 200
    versions = history.get_json()["versions"]
    assert [item["version"] for item in versions] == [1, 2, 3]
    assert versions[2]["title"] == "原始年龄题 v1"


def test_restore_rejects_invalid_or_unrelated_version(client):
    """不能恢复不存在的版本，也不能把另一道题的版本混进来。"""
    register_and_login(client)
    first = create_age_library_question(client, "第一道题")
    second = create_age_library_question(client, "第二道题")

    invalid_id = client.post(
        f"/api/question-library/{first['library_question_id']}/restore",
        json={"target_version_id": "not-an-object-id"},
    )
    assert invalid_id.status_code == 400

    unrelated = client.post(
        f"/api/question-library/{first['library_question_id']}/restore",
        json={"target_version_id": second["library_question_id"]},
    )
    assert unrelated.status_code == 400

    nonexistent = client.post(
        f"/api/question-library/{first['library_question_id']}/restore",
        json={"target_version_id": "000000000000000000000000"},
    )
    assert nonexistent.status_code == 404


def test_non_owner_cannot_restore_shared_question_version(client):
    """共享使用权不包含恢复版本的权限。"""
    owner = register_and_login(client)
    library = create_age_library_question(client, "所有者的题目")

    client.post("/api/auth/logout")
    student = register_and_login(client)

    # 由所有者分享题目给学生。
    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"username": owner, "password": "TestPass123!"},
    )
    assert login.status_code == 200

    share = client.post(
        f"/api/question-library/{library['library_question_id']}/share",
        json={"username": student},
    )
    assert share.status_code == 200, share.get_json()

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"username": student, "password": "TestPass123!"},
    )
    assert login.status_code == 200

    denied = client.post(
        f"/api/question-library/{library['library_question_id']}/restore",
        json={"target_version_id": library["library_question_id"]},
    )
    assert denied.status_code == 403


# -------------------- 任务六：题库使用情况与编辑版本测试 --------------------


def test_question_library_uses_returns_surveys_using_question(client):
    """同一道题被两份问卷使用时，应能查询到两份问卷。"""
    register_and_login(client)
    library = create_age_library_question(client)
    library_id = library["library_question_id"]

    survey1 = create_survey(client, "题目使用情况问卷一")
    survey2 = create_survey(client, "题目使用情况问卷二")

    attached1 = add_library_question(
        client, survey1["survey_id"], library_id
    )
    attached2 = add_library_question(
        client, survey2["survey_id"], library_id
    )

    assert attached1.status_code == 201, attached1.get_json()
    assert attached2.status_code == 201, attached2.get_json()

    response = client.get(
        f"/api/question-library/{library_id}/uses"
    )
    assert response.status_code == 200, response.get_json()

    data = response.get_json()
    assert data["count"] == 2

    used_survey_ids = {
        item["survey_id"] for item in data["uses"]
    }
    assert used_survey_ids == {
        survey1["survey_id"],
        survey2["survey_id"],
    }


def test_question_library_uses_includes_different_versions(client):
    """同一道题的不同版本被使用时，应能汇总查询。"""
    register_and_login(client)
    v1 = create_age_library_question(client, "年龄题 v1")

    v2_response = create_age_version(
        client, v1["library_question_id"], "年龄题 v2"
    )
    assert v2_response.status_code == 201, v2_response.get_json()
    v2 = v2_response.get_json()["question"]

    survey1 = create_survey(client, "使用版本一的问卷")
    survey2 = create_survey(client, "使用版本二的问卷")

    attached1 = add_library_question(
        client, survey1["survey_id"], v1["library_question_id"]
    )
    attached2 = add_library_question(
        client, survey2["survey_id"], v2["library_question_id"]
    )

    assert attached1.status_code == 201, attached1.get_json()
    assert attached2.status_code == 201, attached2.get_json()

    response = client.get(
        f"/api/question-library/{v1['library_question_id']}/uses"
    )
    assert response.status_code == 200, response.get_json()

    data = response.get_json()
    assert data["count"] == 2

    versions_by_survey = {
        item["survey_id"]: item["question_version"]
        for item in data["uses"]
    }
    assert versions_by_survey[survey1["survey_id"]] == 1
    assert versions_by_survey[survey2["survey_id"]] == 2


def test_question_library_uses_requires_login(client):
    """未登录用户不能查询题库题目的使用情况。"""
    response = client.get(
        "/api/question-library/000000000000000000000000/uses"
    )
    assert response.status_code == 401


def test_edit_library_question_creates_new_version(client):
    """通过编辑接口修改题目时，应创建新版本而不是覆盖旧版本。"""
    register_and_login(client)
    v1 = create_age_library_question(client, "原始年龄题")

    response = client.post(
        f"/api/question-library/{v1['library_question_id']}/edit",
        json={
            "create_new_version": True,
            "title": "修改后的年龄题",
            "type": "numeric",
            "required": True,
            "validation": {
                "min_value": 18,
                "max_value": 99,
                "integer": True,
            },
        },
    )

    assert response.status_code == 201, response.get_json()

    data = response.get_json()
    new_question = data.get("question", data)

    assert new_question["version"] == 2
    assert new_question["title"] == "修改后的年龄题"

    old_doc = db.question_library.find_one({
        "_id": __import__("bson").ObjectId(
            v1["library_question_id"]
        )
    })
    assert old_doc is not None
    assert old_doc["version"] == 1
    assert old_doc["title"] == "原始年龄题"


def test_edit_library_question_requires_new_version(client):
    """编辑接口不允许直接覆盖旧版本。"""
    register_and_login(client)
    v1 = create_age_library_question(client)

    response = client.post(
        f"/api/question-library/{v1['library_question_id']}/edit",
        json={
            "create_new_version": False,
            "title": "不应覆盖原题",
            "type": "numeric",
            "required": True,
            "validation": {
                "min_value": 0,
                "max_value": 120,
                "integer": True,
            },
        },
    )

    assert response.status_code in (400, 403), response.get_json()

    old_doc = db.question_library.find_one({
        "_id": __import__("bson").ObjectId(
            v1["library_question_id"]
        )
    })
    assert old_doc is not None
    assert old_doc["title"] == "你的年龄"
    assert old_doc["version"] == 1


def test_edit_library_question_does_not_change_existing_survey(client):
    """编辑题库并创建新版本，不应修改已添加旧版本的问卷。"""
    register_and_login(client)
    v1 = create_age_library_question(client, "问卷原始年龄题")

    survey = create_survey(client, "编辑版本独立性测试")
    attached = add_library_question(
        client, survey["survey_id"], v1["library_question_id"]
    )
    assert attached.status_code == 201, attached.get_json()

    edit = client.post(
        f"/api/question-library/{v1['library_question_id']}/edit",
        json={
            "create_new_version": True,
            "title": "题库更新后的年龄题",
            "type": "numeric",
            "required": True,
            "validation": {
                "min_value": 18,
                "max_value": 99,
                "integer": True,
            },
        },
    )
    assert edit.status_code == 201, edit.get_json()

    listed = client.get(
        f"/api/surveys/{survey['survey_id']}/questions"
    )
    assert listed.status_code == 200, listed.get_json()

    questions = listed.get_json()["questions"]
    saved_question = next(
        q for q in questions
        if q["question_id"] == attached.get_json()["question_id"]
    )

    assert saved_question["title"] == "问卷原始年龄题"
    assert saved_question["question_version"] == 1


def test_non_owner_cannot_edit_shared_library_question(client):
    """拥有共享使用权的用户不能修改他人的题库版本。"""
    owner = register_and_login(client)
    library = create_age_library_question(client)
    library_id = library["library_question_id"]

    client.post("/api/auth/logout")
    student = register_and_login(client)

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={
            "username": owner,
            "password": "TestPass123!",
        },
    )
    assert login.status_code == 200

    share = client.post(
        f"/api/question-library/{library_id}/share",
        json={"username": student},
    )
    assert share.status_code == 200, share.get_json()

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={
            "username": student,
            "password": "TestPass123!",
        },
    )
    assert login.status_code == 200

    response = client.post(
        f"/api/question-library/{library_id}/edit",
        json={
            "create_new_version": True,
            "title": "未经允许的修改",
            "type": "numeric",
            "required": True,
            "validation": {
                "min_value": 0,
                "max_value": 120,
                "integer": True,
            },
        },
    )

    assert response.status_code == 403, response.get_json()

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={
            "username": owner,
            "password": "TestPass123!",
        },
    )
    assert login.status_code == 200

    old_doc = db.question_library.find_one({
        "_id": __import__("bson").ObjectId(library_id)
    })
    assert old_doc is not None
    assert old_doc["title"] == "你的年龄"
    assert old_doc["version"] == 1



# -------------------- 任务八：跨问卷逻辑题统计测试 --------------------


def test_question_stats_merges_responses_across_two_surveys(client):
    """同一道题库逻辑题被两份问卷复用后，应汇总两份问卷的答卷。"""
    register_and_login(client)

    library = create_age_library_question(client, "跨问卷统计年龄题")
    library_id = library["library_question_id"]
    question_key = library["question_key"]

    survey1 = create_survey(client, "跨问卷统计测试一")
    survey2 = create_survey(client, "跨问卷统计测试二")

    attached1 = add_library_question(
        client, survey1["survey_id"], library_id
    )
    attached2 = add_library_question(
        client, survey2["survey_id"], library_id
    )
    assert attached1.status_code == 201, attached1.get_json()
    assert attached2.status_code == 201, attached2.get_json()

    question1_id = attached1.get_json()["question_id"]
    question2_id = attached2.get_json()["question_id"]

    published1 = publish_survey(client, survey1["survey_id"])
    published2 = publish_survey(client, survey2["survey_id"])

    submission1 = client.post(
        f"/api/responses/{published1['share_code']}",
        json={
            "answers": [
                {"question_id": question1_id, "answer": 20}
            ]
        },
    )
    assert submission1.status_code == 201, submission1.get_json()

    submission2 = client.post(
        f"/api/responses/{published2['share_code']}",
        json={
            "answers": [
                {"question_id": question2_id, "answer": 30}
            ]
        },
    )
    assert submission2.status_code == 201, submission2.get_json()

    stats_response = client.get(
        f"/api/responses/question-stats/{question_key}"
    )
    assert stats_response.status_code == 200, stats_response.get_json()

    # 统计数据位于返回 JSON 的 stats 字段中。
    stats = stats_response.get_json()["stats"]

    # 两份问卷均有一份答卷，总答卷数应为 2。
    assert stats["response_count"] == 2

    # 年龄分别为 20 和 30，平均值应为 25。
    assert stats["numeric"]["count"] == 2
    assert stats["numeric"]["average"] == 25


def test_question_stats_includes_responses_from_different_versions(client):
    """同一道逻辑题的不同版本被不同问卷使用时，历史答卷应一并统计。"""
    register_and_login(client)

    v1 = create_age_library_question(client, "版本统计年龄题 v1")

    v2_response = create_age_version(
        client, v1["library_question_id"], "版本统计年龄题 v2"
    )
    assert v2_response.status_code == 201, v2_response.get_json()
    v2 = v2_response.get_json()["question"]

    # 同一道逻辑题的不同版本应共享 question_key。
    assert v1["question_key"] == v2["question_key"]

    survey1 = create_survey(client, "旧版本统计问卷")
    survey2 = create_survey(client, "新版本统计问卷")

    attached1 = add_library_question(
        client, survey1["survey_id"], v1["library_question_id"]
    )
    attached2 = add_library_question(
        client, survey2["survey_id"], v2["library_question_id"]
    )
    assert attached1.status_code == 201, attached1.get_json()
    assert attached2.status_code == 201, attached2.get_json()

    published1 = publish_survey(client, survey1["survey_id"])
    published2 = publish_survey(client, survey2["survey_id"])

    submitted1 = client.post(
        f"/api/responses/{published1['share_code']}",
        json={
            "answers": [
                {
                    "question_id": attached1.get_json()["question_id"],
                    "answer": 22,
                }
            ]
        },
    )
    assert submitted1.status_code == 201, submitted1.get_json()

    submitted2 = client.post(
        f"/api/responses/{published2['share_code']}",
        json={
            "answers": [
                {
                    "question_id": attached2.get_json()["question_id"],
                    "answer": 28,
                }
            ]
        },
    )
    assert submitted2.status_code == 201, submitted2.get_json()

    stats_response = client.get(
        f"/api/responses/question-stats/{v1['question_key']}"
    )
    assert stats_response.status_code == 200, stats_response.get_json()

    stats = stats_response.get_json()["stats"]

    # 两个版本的答卷都应计入同一道逻辑题的统计。
    assert stats["response_count"] == 2
    assert stats["numeric"]["count"] == 2
    assert stats["numeric"]["average"] == 25


def test_question_stats_requires_login(client):
    """未登录用户不能查询跨问卷题目统计。"""
    response = client.get(
        "/api/responses/question-stats/some-question-key"
    )
    assert response.status_code == 401


def test_question_stats_does_not_include_another_users_responses(client):
    """统计结果不应包含其他用户私有问卷中的答卷。"""
    owner = register_and_login(client)

    library = create_age_library_question(client, "用户隔离统计年龄题")
    library_id = library["library_question_id"]
    question_key = library["question_key"]

    owner_survey = create_survey(client, "所有者的统计问卷")
    owner_attached = add_library_question(
        client, owner_survey["survey_id"], library_id
    )
    assert owner_attached.status_code == 201, owner_attached.get_json()

    owner_published = publish_survey(client, owner_survey["survey_id"])
    owner_submission = client.post(
        f"/api/responses/{owner_published['share_code']}",
        json={
            "answers": [
                {
                    "question_id": owner_attached.get_json()["question_id"],
                    "answer": 40,
                }
            ]
        },
    )
    assert owner_submission.status_code == 201, owner_submission.get_json()

    # 切换到第二个用户。
    client.post("/api/auth/logout")
    register_and_login(client)

    # 第二个用户创建自己的普通问卷并提交答卷。
    # 该问卷没有使用所有者的题库逻辑题。
    other_survey = create_survey(client, "另一个用户的私有问卷")
    other_question = add_question(
        client,
        other_survey["survey_id"],
        {
            "title": "其他用户的年龄题",
            "type": "numeric",
            "required": True,
            "validation": {
                "min_value": 0,
                "max_value": 120,
                "integer": True,
            },
        },
    )
    assert other_question.status_code == 201, other_question.get_json()

    other_published = publish_survey(client, other_survey["survey_id"])
    other_submission = client.post(
        f"/api/responses/{other_published['share_code']}",
        json={
            "answers": [
                {
                    "question_id": other_question.get_json()["question_id"],
                    "answer": 99,
                }
            ]
        },
    )
    assert other_submission.status_code == 201, other_submission.get_json()

    # 重新登录所有者，查询所有者自己的统计。
    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={
            "username": owner,
            "password": "TestPass123!",
        },
    )
    assert login.status_code == 200, login.get_json()

    stats_response = client.get(
        f"/api/responses/question-stats/{question_key}"
    )
    assert stats_response.status_code == 200, stats_response.get_json()

    stats = stats_response.get_json()["stats"]

    # 只能统计所有者问卷中的答卷，不能把其他用户的 99 纳入统计。
    assert stats["response_count"] == 1
    assert stats["numeric"]["count"] == 1
    assert stats["numeric"]["average"] == 40
