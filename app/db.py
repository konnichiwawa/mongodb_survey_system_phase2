
import os

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ConfigurationError, PyMongoError

# 加载项目根目录中的 .env 配置。
# 如果系统已经设置环境变量，保留系统环境变量的优先级。
load_dotenv()

MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb://127.0.0.1:27017",
).strip()

MONGO_DB_NAME = os.getenv(
    "MONGO_DB_NAME",
    "survey_system",
).strip()

if not MONGO_URI:
    raise ConfigurationError("MONGO_URI 不能为空。")

if not MONGO_DB_NAME:
    raise ConfigurationError("MONGO_DB_NAME 不能为空。")

# 创建 MongoDB 客户端。
# MongoClient 默认采用延迟连接，因此导入本模块时不会立即访问数据库。
client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=5000,
    appname="mongodb_survey_system",
)

# 选择当前环境对应的数据库。
# 测试环境可以通过 MONGO_DB_NAME 使用独立的测试数据库。
db = client[MONGO_DB_NAME]


def test_connection():
    """检查 MongoDB 是否能够连接，连接失败时返回 False。"""
    try:
        client.admin.command("ping")
        return True
    except PyMongoError:
        return False
