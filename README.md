# 基于 MongoDB 的问卷系统

本项目是“当代数据管理系统”课程大作业，使用 Python、Flask 和 MongoDB 实现简化的在线问卷系统。项目分为两个阶段：第一阶段实现问卷创建、题目配置、发布、答卷提交和统计等核心流程；第二阶段在原有系统基础上扩展题目复用、分享、版本管理、题库和跨问卷单题统计等能力。

> 本 README 面向项目运行、开发和测试。实际接口字段及题目库相关子路由以当前提交版本的源代码和项目文档为准。

## 一、项目功能

### 1.1 第一阶段功能

- 用户注册、登录、退出登录和当前登录状态查询。
- 创建问卷、查询本人创建的问卷、发布和关闭问卷。
- 设置或清除问卷截止时间。
- 创建、查询、修改和删除问卷题目。
- 支持单选题、多选题、文本题和数字题。
- 支持必填校验、重复选项校验、多选数量限制、文本长度限制、数字范围和整数校验。
- 支持单选题、多选题和数字题的条件跳转，并在提交时检查实际答题路径。
- 通过分享码访问已发布问卷并提交答卷。
- 查询单份问卷的答卷数量、选项计数、文本答案和数字统计等结果。

### 1.2 第二阶段扩展

第二阶段围绕需求变更中的八项任务扩展系统：

1. 保存常用题目，并在其他问卷中重复使用。
2. 将题目分享给其他用户使用。
3. 修改题目时保护已经完成或发布的问卷内容。
4. 查看题目修改历史、版本来源，并支持恢复旧版本。
5. 允许同一逻辑题目的不同版本同时存在。
6. 查询某个题目被哪些问卷使用。
7. 建立并管理题库，从题库中选用题目。
8. 按逻辑题目标识汇总不同问卷中的单题回答。

跨问卷单题统计接口：

```http
GET /api/responses/question-stats/<question_key>
```

该接口根据逻辑题目标识聚合符合当前用户统计权限范围的数据。逻辑题目标识与单份问卷中的具体题目标识用途不同，不能混用。

## 二、技术栈与环境要求

| 项目 | 使用技术或说明 |
|---|---|
| 开发语言 | Python |
| 后端框架 | Flask |
| 数据库 | MongoDB |
| Python 数据库驱动 | PyMongo |
| 环境配置 | python-dotenv |
| 登录及密码相关组件 | Flask-Login、Werkzeug（以当前依赖和代码使用情况为准） |
| 自动化测试 | pytest |
| 推荐运行方式 | Python 虚拟环境 `.venv` |

项目开发记录使用过 Python 3.14.7 和 MongoDB Server 8.3.11。其他版本请在实际环境中验证兼容性。

## 三、项目目录

项目主要目录如下，具体文件以最终提交版本为准：

```text
mongodb_survey_system/
├── app/
│   ├── routes/
│   │   ├── auth.py                 # 用户认证相关接口
│   │   ├── surveys.py              # 问卷管理、发布、分享和问卷统计
│   │   ├── questions.py            # 问卷内题目管理
│   │   ├── responses.py            # 答卷提交、答案校验、跳转和统计
│   │   └── question_library.py     # 第二阶段题目库相关业务
│   ├── models/                     # 模型相关模块（如当前版本包含）
│   ├── services/                   # 业务服务模块（如当前版本包含）
│   ├── static/                     # 静态资源
│   ├── templates/                  # 页面模板
│   ├── db.py                       # MongoDB 连接与数据库选择
│   ├── init_db.py                  # 数据库集合和索引初始化
│   └── __init__.py                 # Flask 应用创建和路由注册
├── docs/                           # 项目文档、测试用例、完成报告等
├── tests/
│   └── test_api.py                 # API 自动化测试
├── scripts/                        # 辅助脚本（如当前版本包含）
├── instance/                       # 实例目录（如当前版本包含）
├── .env.example                    # 环境变量配置模板
├── requirements.txt                # Python 依赖清单
├── run.py                          # 应用启动入口
└── README.md                       # 项目说明和运行指南
```

主要入口文件职责：

- `run.py`：启动 Flask 应用。
- `app/__init__.py`：创建应用、注册路由并提供首页或健康检查等基础功能。
- `app/db.py`：读取 MongoDB 配置并建立数据库连接。
- `app/init_db.py`：创建项目所需集合和索引。
- `app/routes/`：按照业务模块组织认证、问卷、题目、答卷和题库相关接口。
- `tests/test_api.py`：通过 Flask 测试客户端验证后端 API 行为。

## 四、MongoDB 数据模型

MongoDB 使用文档模型保存数据。项目主要按业务对象划分集合，避免把用户、问卷、题目和全部答卷放进一个大型集合或文档。

### 4.1 核心集合

| 集合 | 主要数据 | 用途 |
|---|---|---|
| `users` | 用户名、密码哈希及认证相关信息 | 注册、登录和身份识别 |
| `surveys` | 创建者、标题、描述、匿名设置、状态、分享码、截止时间和时间字段等 | 问卷生命周期和归属管理 |
| `questions` | 所属问卷、标题、题型、选项、必填配置、校验规则、跳转规则和题目顺序等 | 保存问卷中的题目配置 |
| `responses` | 所属问卷、提交者标识、答案列表和提交时间等 | 保存答卷并提供统计数据 |

第二阶段还需要表达逻辑题目标识、题目版本、题目分享、题库及题目使用关系等业务概念。这些概念不一定分别对应独立的物理集合；具体存储位置和字段以当前版本中的数据库操作代码为准。

### 4.2 主要关联关系

```text
users
  └── surveys（creator_id）
        ├── questions（survey_id）
        └── responses（survey_id）

逻辑题目（question_key）
  ├── 关联相关的题目或版本
  └── 用于跨问卷单题统计
```

- `survey_id` 用于关联问卷与其题目或答卷。
- 具体题目标识用于定位一条题目记录。
- `question_key` 用于跨问卷识别同一逻辑题目。
- 数据库中的业务标识关联不等同于关系数据库的外键约束，关联有效性和操作权限需要由后端检查。

### 4.3 嵌入式数据

题目的选项、校验规则和跳转规则与题目本身关系紧密，适合按照当前数据结构放在题目文档内；一次答卷中的多个答案共同组成一次提交，可以放在该答卷文档的 `answers` 数组中。这样既能保持业务对象的职责边界，也能减少读取题目或单份答卷时不必要的数据查询。

### 4.4 索引与初始化

数据库初始化代码 `app/init_db.py` 会创建核心集合以及常用索引。第一阶段已记录的索引包括：

- `users.username` 唯一索引：避免用户名重复。
- `surveys.share_code` 唯一索引：避免问卷分享码重复。
- `surveys.creator_id` 与 `created_at` 组合索引：支持查询某用户创建的问卷。
- `questions.survey_id` 与 `order` 组合唯一索引：约束同一问卷内题目顺序值不重复。
- `responses.survey_id` 与 `submitted_at` 组合索引：支持按问卷查询答卷及提交时间。
- `responses.submission_key` 稀疏唯一索引：仅对包含该字段的文档施加相应唯一性约束。该索引本身不代表系统已实现防重复提交，实际行为取决于提交代码是否写入并使用该字段。

第二阶段新增业务字段是否建立了额外索引，应以最终版 `app/init_db.py` 为准。

## 五、运行前准备

运行本项目需要：

1. 安装 Python，并能够在终端中执行 `python`。
2. 安装并启动 MongoDB Server。
3. 获取完整项目代码。
4. 安装 `requirements.txt` 中列出的 Python 依赖。
5. 在项目根目录创建并配置 `.env` 文件。

以下示例以 Windows PowerShell 为主。

## 六、安装与配置

### 6.1 获取项目并进入目录

如果从 GitHub 获取项目：

```powershell
git clone https://github.com/konnichiwawa/mongodb_survey_system.git
cd mongodb_survey_system
```

如果已经收到项目压缩包，先解压，再在 PowerShell 或 VS Code 终端中进入包含 `run.py` 和 `requirements.txt` 的项目根目录。

### 6.2 创建并启用虚拟环境

如果尚未创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

如果 `.venv` 已存在，则在项目根目录执行：

```powershell
.\.venv\Scripts\Activate.ps1
```

激活成功后，终端提示符前通常会出现 `(.venv)`。如果 PowerShell 阻止执行激活脚本，可仅对当前终端进程临时调整执行策略：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 6.3 安装 Python 依赖

在项目根目录运行：

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

依赖清单以 `requirements.txt` 为准。若安装失败，请先检查 Python 版本、网络连接和具体报错信息。

### 6.4 配置环境变量

项目使用 `python-dotenv` 读取项目根目录中的 `.env`。如果尚无 `.env`，可复制模板：

```powershell
Copy-Item .env.example .env
```

如果 `.env` 已存在，不要直接覆盖，以免丢失已有配置。

典型配置如下：

```dotenv
SECRET_KEY=replace-with-a-random-secret
MONGO_URI=mongodb://127.0.0.1:27017
MONGO_DB_NAME=survey_system
```

配置项说明：

| 配置项 | 作用 | 示例值 |
|---|---|---|
| `SECRET_KEY` | Flask 会话等功能使用的签名密钥 | 自行生成的随机密钥 |
| `MONGO_URI` | MongoDB 服务连接地址 | `mongodb://127.0.0.1:27017` |
| `MONGO_DB_NAME` | 应用运行时使用的数据库名称 | `survey_system` |

注意：

- `127.0.0.1` 表示本机，`27017` 是常见的 MongoDB 默认端口。
- `MONGO_DB_NAME` 是数据库名称，不是 MongoDB 数据文件目录。
- `SECRET_KEY` 应替换为随机且独立的密钥；不要将真实密钥上传到公开仓库。
- `.env` 保存本地配置，不应提交含真实密钥的文件；应保留 `.env.example` 作为模板。

## 七、启动 MongoDB 与应用

### 7.1 启动 MongoDB

请先确认本机 MongoDB Server 已安装。若 MongoDB 已注册为 Windows 服务，可以通过“服务”管理工具启动对应服务；服务名称取决于本机安装方式。

若使用命令行启动，请先确保数据目录存在。以下是示例路径，需替换成自己电脑中的实际安装路径和数据目录：

```powershell
New-Item -ItemType Directory -Force -Path "D:\MongoDB\data\db"
& "D:\MongoDB\Server\8.3\bin\mongod.exe" --dbpath "D:\MongoDB\data\db" --port 27017
```

如果 `mongod` 已加入系统 `PATH`，也可以根据本机 MongoDB 的配置使用 `mongod --dbpath ...` 启动。

启动后应保持 MongoDB 终端运行。不要为了重新运行项目而删除数据库数据目录，因为其中可能保存已有问卷和答卷数据。

### 7.2 初始化集合和索引

首次配置项目时，在另一个终端进入项目根目录，激活虚拟环境，然后执行：

```powershell
.\.venv\Scripts\Activate.ps1
python -m app.init_db
```

该命令会根据 `app/init_db.py` 创建或检查项目需要的核心集合与索引。应用创建函数不会自动代替该初始化脚本，因此首次运行前应执行初始化步骤。

初始化前后均应确认 `.env` 中的 `MONGO_URI` 和 `MONGO_DB_NAME` 指向预期数据库。已有数据时，不要随意删除集合或索引。

### 7.3 启动 Flask 后端

在项目根目录执行：

```powershell
.\.venv\Scripts\Activate.ps1
python run.py
```

若虚拟环境已经激活，直接运行 `python run.py` 即可。按当前项目开发配置，服务默认地址为：

```text
http://127.0.0.1:5000
```

开发服务器适用于本地开发和测试，不应直接作为生产环境服务器使用。

### 7.4 检查服务状态

在浏览器中访问：

```text
http://127.0.0.1:5000/health
```

正常情况下，健康检查返回 HTTP 200，并提供服务及 MongoDB 连接状态等信息。如果检查失败，请确认 MongoDB 正在运行、`MONGO_URI` 正确、端口可访问，并且后端读取了预期的 `.env` 配置。

## 八、主要 API 概览

以下是主要接口组。具体请求体、响应字段、权限规则和错误状态以项目当前代码及详细 API 文档为准。

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/` | 查询后端运行信息 |
| `GET` | `/health` | 检查服务及 MongoDB 连接状态 |
| `POST` | `/api/auth/register` | 注册用户 |
| `POST` | `/api/auth/login` | 登录 |
| `POST` | `/api/auth/logout` | 退出登录 |
| `GET` | `/api/auth/me` | 查询当前登录状态 |
| `POST` | `/api/surveys` | 创建问卷 |
| `GET` | `/api/surveys` | 查询当前用户的问卷列表 |
| `POST` | `/api/surveys/<survey_id>/publish` | 发布问卷 |
| `POST` | `/api/surveys/<survey_id>/close` | 关闭问卷 |
| `PUT` | `/api/surveys/<survey_id>/deadline` | 设置或清除问卷截止时间 |
| `GET` | `/api/surveys/share/<share_code>` | 通过分享码访问已发布问卷 |
| `GET` | `/api/surveys/<survey_id>/stats` | 查询单份问卷的统计结果 |
| `POST` | `/api/surveys/<survey_id>/questions` | 创建问卷题目 |
| `GET` | `/api/surveys/<survey_id>/questions` | 查询问卷题目 |
| `PUT` | `/api/surveys/<survey_id>/questions/<question_id>` | 修改问卷题目 |
| `DELETE` | `/api/surveys/<survey_id>/questions/<question_id>` | 删除问卷题目 |
| `POST` | `/api/responses/<share_code>` | 提交答卷 |
| `GET` | `/api/responses/question-stats/<question_key>` | 跨问卷单题统计（第二阶段） |

第二阶段题目库蓝图使用 `/api/question-library` 作为路由前缀。题目保存、分享、版本管理、使用情况查询和题库操作的具体子路由，请以当前版本 `app/routes/question_library.py` 的实现及详细 API 文档为准，不应只根据本 README 推断未列出的子路由。

## 九、运行自动化测试

确认 MongoDB 服务正常，并在项目根目录激活虚拟环境。

### 9.1 运行完整测试

```powershell
python -m pytest -v
```

也可以运行指定测试文件：

```powershell
python -m pytest tests/test_api.py -v
```

第二阶段开发过程中最近一次记录的完整测试结果为：

```text
40 passed in 9.90s
```

这是开发过程中的已记录结果。提交前应在最终代码状态下重新运行测试，并以实际终端输出为准。

### 9.2 只运行跨问卷单题统计相关测试

```powershell
python -m pytest tests/test_api.py -v -k "question_stats"
```

最近一次记录的输出摘要为：

```text
4 passed, 36 deselected
```

该筛选命令只运行名称匹配 `question_stats` 的测试，其余测试会被跳过；这四项结果不能与完整测试数量重复相加。

### 9.3 测试数据库注意事项

当前测试代码在导入应用前将测试数据库名称设置为 `survey_system_test`，并在测试开始前清理、测试结束后再次清理 `users`、`surveys`、`questions` 和 `responses` 集合中的测试数据。因此：

- 测试前应确认 MongoDB 服务可用。
- 不要修改测试配置，使测试误连到需要保留数据的开发数据库。
- 运行测试前确认测试配置确实使用 `survey_system_test`。
- 若后续修改测试清理逻辑或增加集合，应同时检查测试数据清理范围。

## 十、相关项目文档

项目的详细资料建议统一放在 `docs/` 目录中，至少包括：

- **项目文档：** 系统说明、MongoDB 数据库设计、API 接口说明和关键逻辑说明。
- **测试用例：** 测试目的、测试环境、前置条件、输入、测试步骤、预期输出、实际输出和测试结果。
- **项目完成报告：** 第一阶段设计、第二阶段需求分析、数据结构与程序修改、兼容性、旧功能保障、MongoDB 设计和测试结果。
- **AI 使用日志：** 使用工具、提示词、AI 输出、是否修改、修改内容、错误及人工核对过程。

提交前请确保 README、详细文档、测试代码和实际运行方式一致，并检查 `docs/` 中的文件名称与文档内引用相匹配。

## 十一、常见问题

### 11.1 `/health` 返回数据库连接失败

检查 MongoDB 是否已启动、连接地址是否正确、端口是否匹配，以及 `.env` 是否位于项目根目录。修改 `.env` 后应重新启动 Flask 应用。

### 11.2 执行 `python -m app.init_db` 失败

确认当前终端位于包含 `run.py` 和 `app/` 的项目根目录，虚拟环境已经激活，并且 MongoDB 可以连接。

### 11.3 `flask run` 找不到应用或启动异常

本项目建议直接使用 `python run.py` 启动。若终端中的 `flask.exe` 指向旧的虚拟环境路径，使用当前虚拟环境执行 `python -m ...` 或直接运行项目入口，避免调用旧环境中的启动器。

### 11.4 自动化测试失败或数据异常

先查看失败测试的名称、断言和响应信息，确认 MongoDB 已启动并且测试库名称正确。测试执行过程中会清理测试数据库的核心集合，不应让测试指向需要保留业务数据的数据库。

## 十二、开发与安全注意事项

- 不要将 `.env` 中的真实密钥提交到公开代码仓库。
- 不要删除 MongoDB 数据目录来解决一般启动问题。
- 数据库初始化脚本与应用启动是两个不同步骤，首次配置时需要单独初始化集合和索引。
- 题目资源分享、题目版本和跨问卷统计涉及权限及数据关联，修改相关代码后应运行相应测试。
- 不要把 `submission_key` 稀疏唯一索引直接理解为已经实现防重复提交；实际效果取决于提交逻辑是否配套使用该字段。
- README 描述的是项目整体入口和运行方式；具体字段、API 子路由和错误响应应以最终源代码为准。

---

本项目通过两个阶段的开发，先完成问卷系统的核心业务流程，再围绕题目复用、分享、版本管理、题库和跨问卷单题统计扩展原有能力。代码、数据库初始化、环境配置、自动化测试和项目文档共同构成完整的课程项目提交材料。
