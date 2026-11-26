# 人格狼人杀实验室 · MBTI × Werewolf Lab

用一个受控的 9 / 10 人狼人杀局，测出「人格标签 → 行为参数 → 胜率」这条链。

- 玩家来自 **AudienceLib** 授权人口库，可按国家、年龄、性别、城乡、学历、职业、消费风格筛选；入库后可重新测验或删除。
- 每位玩家由 **DeepSeek** 以人物身份完成人格问卷；第一版是 **93 题 MBTI 问卷**（题目与计分规则来自 `reference/mbti-test-93.html`），结果与该玩家绑定。
- 支持上传多套问卷，每套问卷为每位玩家保存独立结果；玩家库可切换当前生效问卷，问卷管理页可批量补测、删除和两两对比。
- 模拟按详细方案中的规则运行：9 人局 3 狼 / 3 民 / 预女猎；10 人局增加 1 个平民位（4 民），其余角色和屠边规则不变，8 轮未决。
- 每局所有变量角色共享同一性格标签，其余角色固定；逐局轮换变量性格，观察胜率变化。
- 逐局复盘可以看到夜间行动、每句发言、投票、猎人开枪和胜负原因；点击发言可以打开该玩家本轮的内心思考浮层（赛后可见）。
- 历史记录保留每次模拟的配置、固定角色、变量性格、逐局结果和完整统计。
- 登录采用邀请制邮箱验证码：首次注册需要邀请码，注册成功后只需邮箱 + 验证码。所有数据和模型调用接口都在登录后访问。

## 登录与访问控制

- 登录和注册是同一个入口。首次使用输入邮箱 + 邀请码，验证码发到邮箱后完成注册并登录；之后同一邮箱只需输入邮箱，验证码会再次发到邮箱。
- 验证码 6 位、10 分钟有效、单次使用、最多错 6 次；同一邮箱 60 秒冷却、每小时最多 5 封。
- 邀请码可以反复使用，配置在 `backend/config/auth.json` 的 `invite_codes` 里；新增邀请码后重启服务生效。每个用户使用的邀请码记录在 `users.invite_code`，便于审计。
- 会话使用 HttpOnly Cookie（默认 30 天）。部署到 HTTPS 时把 `cookie_secure` 设为 `true`，或让反向代理传入 `X-Forwarded-Proto: https`。
- 除了 `/api/health` 和 `/api/auth/*`，所有 API 都需要登录；静态登录页公开，但玩家库、模拟、历史接口都会返回 401。
- 登录只做访问控制，**不按用户隔离数据**：所有受邀用户看到同一个玩家库和同一份历史记录。如果以后要做多租户，需要给 players/simulations 增加 user_id。
- 跨域开发时默认只允许 8791/5179 两个本地来源；其他前端地址通过 `WEREWOLF_ALLOWED_ORIGINS`（逗号分隔）配置。
- 邮件通过 `backend/config/smtp.json` 的发件账号发送（模板见 `smtp.example.json`）。未配置 SMTP 或设置 `WEREWOLF_MAIL_MODE=dry_run` 时，验证码写入 `backend/data/outbox/` 并打印到服务端日志，便于本地联调；真实 SMTP 模式不会在接口响应里返回验证码。

## 多套问卷

### 当前生效问卷

玩家库顶部有“生效问卷”下拉框。切换后：

- 玩家卡片、四维图、类型筛选和行为参数都读取该问卷的结果；
- 尚未完成该问卷的玩家显示“未测”，不会借用其他问卷的结果；
- 新抽样任务默认使用该问卷；
- 新建模拟会锁定当时的生效问卷，之后切换问卷不会改变已创建模拟。

第一套内置问卷是 **MBTI 93 题（第一版）**，不可删除，作为上传模板。问卷管理页路径是 `#/questionnaires`，支持：

- 上传 JSON 问卷；
- 对全部尚未测过该问卷的玩家批量测试（已测玩家自动跳过）；
- 查看覆盖率（已测玩家 / 全部玩家）；
- 删除非内置问卷（会级联删除该问卷的结果）；
- 勾选恰好两套问卷进入对比页，只统计同时拥有两套结果的玩家，展示一致/不一致人数、占比和 `[问卷 1 结果 vs 问卷 2 结果]` 分布，并可查看玩家名单。

### 问卷 JSON 格式

当前支持两种作答形式：

- `response_type: "binary"`：每题 A/B 二选一；
- `response_type: "likert5"`：每题 1–5 五度量表，选项 1–5 分别映射到维度极点。

完整格式可用问卷管理页的“下载模板”获取，binary 核心结构如下：

```json
{
  "schema": "werewolf-questionnaire/v1",
  "name": "示例问卷",
  "version": "1.0",
  "kind": "generic",
  "response_type": "binary",
  "description": "说明",
  "dimensions": [
    {"key": "AB", "left": "A", "right": "B", "left_name": "甲", "right_name": "乙"}
  ],
  "questions": [
    {
      "id": 1,
      "text": "题干",
      "options": {
        "A": {"text": "选项 A", "scores": {"AB": "A"}},
        "B": {"text": "选项 B", "scores": {"AB": "B"}}
      }
    }
  ],
  "scoring": {
    "result_order": ["AB"],
    "type_names": {"A": "甲型", "B": "乙型"},
    "params": {"mode": "mbti"}
  }
}
```

- `questions[].id` 必须从 1 开始连续编号。
- `response_type="binary"` 时，每题必须提供 A、B 两个选项；`response_type="likert5"` 时，每题必须提供 1、2、3、4、5 五个选项。
- `scores` 的 key 必须是 `dimensions[].key`，value 必须是该维度的 `left` 或 `right`；中立项可写空对象。
- 五度量表可以把 1–2 映射到左侧、4–5 映射到右侧、3 作为中立；也可以给选项加 `"weight": 2` 做加权。
- `scoring.mode` 支持四种计分方式：
  - `pole_majority`：默认，选项映射维度极点，按左右得分多数决；
  - `dimension_bands`：选项用 `values` 给各维度累加数值，再用 `scoring.bands` 的区间把每个维度映射成标签；
  - `total_bands`：所有题用 `points` 累加总分，再用 `scoring.total_bands` 的总分区间映射结果；
  - `highest_dimension`：各维度累加数值，取最高维度作为结果。
- 每个维度按两侧得分取多数，结果按 `scoring.result_order` 拼接；例如 MBTI 的结果是四个字母。
- 五度量表可以每题写 `"dimension": "JP"` 和 `"reverse": true`，让系统按 1–5 自动累加并处理反向题，也可以逐个选项写 `values`。
- `scoring.params.mode="mbti"` 时，四字母结果会套用 MBTI 的 7 个行为参数；其他问卷默认使用 0.5 基线参数，也可以在 `scoring.params` 中以结果代码为 key 提供参数对象。
- 五度量表示例：

```json
{
  "response_type": "likert5",
  "questions": [
    {
      "id": 1,
      "text": "我更喜欢提前安排好事情",
      "options": {
        "1": {"text": "非常不同意", "scores": {"JP": "P"}},
        "2": {"text": "不同意", "scores": {"JP": "P"}},
        "3": {"text": "一般", "scores": {}},
        "4": {"text": "同意", "scores": {"JP": "J"}},
        "5": {"text": "非常同意", "scores": {"JP": "J"}}
      }
    }
  ]
}
```

- 当前 `backend/mbti_questions.json` 这种旧格式也可以直接上传，系统会自动转换为 binary 结构。

### 数值计分示例

维度分段（例如大五人格的某维度）：

```json
{
  "scoring": {
    "mode": "dimension_bands",
    "result_order": ["O"],
    "bands": {
      "O": [
        {"min": 0, "max": 3, "label": "L"},
        {"min": 4, "max": 10, "label": "H"}
      ]
    }
  },
  "questions": [
    {
      "id": 1,
      "text": "示例题",
      "options": {
        "A": {"text": "低", "values": {"O": 1}},
        "B": {"text": "高", "values": {"O": 5}}
      }
    }
  ]
}
```

总分分段：

```json
{
  "dimensions": [],
  "scoring": {
    "mode": "total_bands",
    "result_order": [],
    "total_bands": [
      {"min": 0, "max": 5, "label": "L"},
      {"min": 6, "max": 20, "label": "H"}
    ]
  },
  "questions": [
    {"id": 1, "text": "示例题", "options": {
      "A": {"text": "低", "points": 1},
      "B": {"text": "高", "points": 5}
    }}
  ]
}
```

### 上传校验

上传问卷时，后端会在写入数据库前调用 `normalize_definition` 做完整校验；任何一项不通过都会返回具体题号或字段的错误，不会保存半成品问卷。

校验包括：

- `schema`、`response_type`、`scoring.mode` 是否受支持；
- 题目 id 是否从 1 连续编号、是否重复；
- binary 是否每题刚好 A/B；likert5 是否每题刚好 1–5；
- 维度 key 是否重复、选项引用的维度和极点是否存在；
- 每个选项的 `scores` / `values` / `points` / `weight` 类型和数值是否合法；
- `pole_majority` 每题是否至少有一个有效 `scores`；
- `dimension_bands` / `highest_dimension` 每题是否有 `values` 或 `dimension`；
- `total_bands` 每题是否有非零 `points` 或 `values`；
- `result_order` 是否引用已有维度、非 total 模式是否非空；
- `bands` / `total_bands` 的 min/max 是否合法、区间是否重叠；
- `scoring.bands` 是否覆盖 `result_order` 需要的维度。

### AI Agent 转换 Prompt

HTML、Word、PDF 等原始问卷可以先交给 AI Agent 转换成上述 JSON。可直接复制的 Prompt 在
[docs/questionnaire-conversion-prompt.md](docs/questionnaire-conversion-prompt.md)。

转换 Prompt 要求 Agent：

- 只输出合法 JSON，不补题、不改题意、不猜测计分；
- 根据原问卷选择 binary（A/B）或 likert5（1–5）；
- binary 每题必须是 A/B；likert5 每题必须是 1–5 五个选项；
- 题目 id 从 1 连续编号；
- 根据原计分规则选择 `pole_majority`、`dimension_bands`、`total_bands` 或 `highest_dimension`；
- 无法转换的题（三选项、七度量表、排序、填空等）返回错误 JSON，而不是强行转换。

## 运行

```bash
cd werewolf
./start.sh
# 打开 http://127.0.0.1:8791
```

首次运行如果 `frontend/dist` 不存在，`start.sh` 会自动执行 `build.sh`。本机 Node 路径默认是：

```bash
/Users/xuning/.workbuddy/binaries/node/versions/22.22.2-6/bin
```

如果 Node 在别处，先设置 `NODE_BIN=/path/to/node/bin`。

其他脚本：

```bash
./build.sh     # 安装依赖 + TypeScript 检查 + 构建
./status.sh    # 查看 API 健康状态
./stop.sh      # 停止 API
```

开发模式（前端热更新）：

```bash
npm --prefix frontend run dev   # http://127.0.0.1:5179，/api 代理到 8791
python3 backend/server.py       # API
```

## 配置

密钥在 `backend/config/model.json`（已被 `.gitignore` 忽略）：

```json
{
  "model": "deepseek-flash",
  "api_key": "sk-...",
  "audiencelib_api_key": "al_live_..."
}
```

模板见 `backend/config/model.example.json`。数据库默认在 `backend/data/werewolf.db`，删除该文件即可清空玩家库、历史记录和登录账号。

登录相关配置：

- `backend/config/auth.json`：邀请码、会话密钥、验证码 TTL、重发间隔、Cookie 名称/安全开关。模板 `auth.example.json`。
- `backend/config/smtp.json`：发件 SMTP 账号。模板 `smtp.example.json`。这两个文件都已加入 `.gitignore`。
- 修改 `invite_codes` 后需要重启 API；邀请码不会因为被使用而失效。

## 目录

```
backend/
  server.py            HTTP API + 静态前端托管
  store.py             SQLite 持久化（players / simulations / games / users / sessions / auth_codes）
  auth.py              邀请制邮箱验证码、会话 Cookie、限流
  mailer.py            SMTP 验证码邮件（可 dry-run 到 outbox）
  profiler.py          AudienceLib 抽样、人物归一化、问卷访谈任务
  questionnaires.py    问卷定义、上传校验、计分、批量测试和对比
  mbti.py              题库计分、类型名称、7 个行为参数推导
  llm.py               DeepSeek JSON 客户端（重试、错误分类）
  engine.py            硬编码裁判的 9/10 人狼人杀引擎
  simulation.py        后台模拟线程、暂停/停止、逐局统计
  audiencelib_client.py  AudienceLib 单文件 SDK
frontend/
  src/pages/           登录、玩家库、模拟台、历史记录
  src/components/      对局复盘抽屉、统计面板、图表、玩家卡
  src/styles.css       纸感实验台 + 深色复盘控制台
tests/
  test_auth.py         邀请码、验证码、会话 Cookie、公开/私有 API 分类
  test_core.py         MBTI 计分、胜负判定、猎人毒杀、提示词隔离、配置校验、统计
  test_runner.py       并发局数、进度计数、逐局落库
  test_questionnaires.py 问卷格式、覆盖率、批量补测、对比和模拟锁定
```

## 规则要点

| 情况 | 处理 |
|---|---|
| 板子 | 9 人：3 狼 / 3 民 / 预女猎；10 人：3 狼 / 4 民 / 预女猎 |
| 判胜 | 狼胜：三神全灭或全部平民出局；好人胜：三狼全灭 |
| 未决 | 8 轮仍未分胜负 |
| 平票 | 直接进入黑夜，无人出局 |
| 女巫 | 解药、毒药各一瓶；同夜不能双药；首夜可自救，之后不能 |
| 猎人 | 被刀或被投出可开枪；被毒死不能开枪 |
| 遗言 | 只有被投出者有 1 句遗言 |
| 发言顺序 | 首夜从 1 号开始；后续从上一轮死者下一位开始 |

裁判模块是硬编码的：夜间顺序、药水合法性、投票计票、猎人开枪和胜负判定都由代码计算，模型只负责选择行动和生成发言。模型输出不合法时会走确定性兜底，并在该局标记 `degenerate`，不会中断整批。

## 人格参数

MBTI 不直接写进发言 prompt 当形容词，而是由四个维度推导出 7 个参数（基线 0.5，偏移 0.3）：

| 参数 | 驱动维度 | 高值 |
|---|---|---|
| `verbosity` 话量 | E / I | E |
| `challenge` 质疑频率 | E / I | E |
| `evidence` 证据依赖 | S / N | S |
| `ally_speed` 结盟时机 | T / F | F |
| `conformity` 跟票倾向 | T / F | F |
| `jump_threshold` 跳身份阈值 | J / P | P（越晚跳） |
| `risk` 风险偏好 | J / P | P |

93 题访谈会使用人物档案和人口库的 Big Five 分数做「作答校准」。原因是人物 prompt 里常写「题多就不耐烦」，如果不校准，大多数人物都会收敛到 ISTJ，人格实验就失去变量。校准只影响作答倾向，计分仍严格按 93 题标准规则。

## 测试

```bash
PYTHONPATH=backend python3 -m unittest discover -s tests -v
```

当前 34 个测试覆盖：登录/邀请码/会话、题库完整性、全 A / 全 B 计分、参数推导、整局跑通、三种胜负条件、毒杀猎人不开枪、猎人放弃开枪、提示词隔离（每个 agent 只能看到自己的身份块）、变量角色人数校验、2000 局上限、并发 runner、统计聚合、9/10 人板子校验、出局信息边界、狼队夜聊和投票理由、多问卷结果/覆盖率/补测/对比/五度李克特/维度分段/总分分段/最高维度/上传规则校验。

## 行为一致性修复

针对 10 局复盘里暴露的问题，引擎增加了这些硬约束：

- **状态注入**：每次发言、投票、夜间行动、遗言都会带上当前存活/出局名单和“出局不翻牌”的信息边界。
- **越界检测**：发言提到已出局者并要求其发言/验人/带队、把遗言当翻牌、狼人自曝、刚报身份又说藏着、女巫谎报药水时，会重写一次；重写失败则走安全兜底。
- **发言→投票一致**：发言 JSON 里记录 `vote_intent`，投票 prompt 会带上本轮发言和承诺；改票必须给理由，说“先听”且没点人可以选择弃票。复盘页显示每票理由和“改票/说等却投”标记。
- **狼队夜聊**：每晚先由每名狼提出刀口和悍跳建议，再由狼队主心骨确定统一刀口、悍跳人和白天策略；白天狼人按计划行动，才会有“对跳”。
- **结构化字段**：`claimed_role` 只在明确“我跳 X”时设置；`accused` 只抓语义上的怀疑对象，不再把一句话里出现的所有号码都算指认。
- **遗言约束**：狼人遗言不得自曝/卖队友；好人可以报身份和验人；遗言不是系统翻牌。
- **开枪约束**：猎人开枪必须优先打自己公开怀疑的人；改枪需要给理由，复盘页展示枪口理由。
- **首夜行为**：预言家首夜不再固定验 1 号；女巫首夜不再默认必救；狼人开始有统一夜间计划。

## 速度与并发

实测本地 28 局历史样本：单局平均 **36.7 秒、84k tokens**。时间主要花在白天 9 人顺序发言；投票和夜间狼刀已经是并行调用，女巫/预言家也已并行。

模拟设置里新增 **并发局数 1–4**（默认 2）：

- 基准（顺序）：4 局约 147 秒，36.7 秒/局。
- 并发 2：4 局实测 **88.5 秒**，折合 **22.1 秒/局**，约 **1.66×**。
- 并发 4：4 局实测 **38.2 秒**，折合 **9.6 秒/局**，约 **3.8×**；其中 1 局出现兜底，说明 4 局并发时 API 峰值已经偏高。
- 并发只并行不同对局，不改变单局规则；总 token 基本不变，批次墙钟时间按并发数下降。
- 并发越高，DeepSeek 的峰值请求数越高；遇到 429 会触发重试/兜底。建议先用 2–3 局观察稳定性，4 局适合赶时间但可能出现单局兜底。
- 发言必须顺序执行，否则后发言的 agent 会听到“未来的信息”；这是不并行化发言的原因。
- 连接复用实测只有约 5% 的延迟收益，因此没有作为主要优化；主要收益来自跨局并发和夜间动作并行。

## 已知限制

- 这是受控模拟，不是真人调查；结论只能说「在我们的模拟里」。
- 种子可复现座位、阵容轮换和引擎随机（平票、狼刀分歧、兜底选择），但模型采样温度不为 0，同样的种子不保证逐字复现同一局发言。
- 单局通常 30–90 秒、6–12 万 tokens，具体取决于轮次和发言长度。2000 局是上限，不是建议值。
- 并发受 DeepSeek 速率限制影响；4 局并发遇到 429 会触发重试/兜底，建议先用 2 局。
- 固定阵容只选一套时，容易出现「狼胜率锁死」。方案里建议 3 套阵容轮换；当前产品按需求锁定单套固定玩家，建议在正式实验时手动开多个批次。
- 变量角色共享一个性格标签，因此「3 狼 + 预言家」这类跨阵营变量会同时影响两个阵营；统计面板会分别给出狼人方/好人方胜率，并额外给出变量玩家自身胜率。
- 登录仅做访问门禁，不做账号级数据隔离；邀请码泄露时请立即修改 `backend/config/auth.json` 并重启。
