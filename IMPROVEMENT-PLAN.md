# BrainGraph 改进方案

> 基于 2026-05-03 社区技术反馈 + 自审
> 状态：待执行

---

## 一、当前问题诊断（实事求是）

### 1.1 "宣传大于落地"——README 过度承诺

**现状：** README 写 "Directly reads Hermes Agent fact_store"，但实际只支持一种固定 schema。用户拿一个不同结构的 SQLite 来，直接报错。

**问题本质：** 没有做 schema 自动探测。Hermes 的 fact_store 有固定表结构，但 Claude Code、Mem0 等其他工具的记忆 DB 结构完全不同。

### 1.2 "只能看表层"——图谱几乎没有边

**现状：** 只靠 `[[wikilinks]]` 和"共享 fact 的实体"连边。大多数用户没有手动 wikilink 的习惯。

**数据：** 改进前 Team-A 637节点只有11条边（1.7%连接率），Team-B/C 完全0边。

**app.py 已改进：** 加了关键词重叠自动关联，连接率大幅提升。但 GitHub 仓库的适配器代码（adapters/）还没同步这个改进。

### 1.3 前端功能偏基础

**现有功能：** 搜索、过滤（按类型）、局部图（depth 1-3）、PNG导出、暗色主题
**缺失功能：**
- 没有按边类型着色（wikilink vs keyword vs entity）
- 没有目录折叠（大目录下节点挤在一起）
- 没有节点详情面板（点击节点看不到内容）
- 没有统计面板（总节点/边/类型分布）
- 没有时间维度（文件创建时间线）

### 1.4 适配器不够健壮

**sqlite_adapter.py：**
- 假设固定表名（entities/facts/fact_entities）
- 假设固定字段名（entity_id/name/entity_type/fact_id/content）
- 没有错误处理：表不存在时直接崩溃

**markdown_adapter.py：**
- 只靠 [[wikilinks]]，没有关键词/标题关联
- 没有从 YAML frontmatter 提取 tags
- 没有同目录关联

---

## 二、改进方案（按优先级）

### 🔴 P0 — 必须马上改（影响用户第一印象）

#### P0-1：SQLite 适配器 schema 自动探测

**文件：** `adapters/sqlite_adapter.py`

**方案：**
```python
# 启动时探测 schema
def _detect_schema(self, conn):
    """自动探测 SQLite 表结构，不假设固定表名/字段名"""
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    
    # 策略1：找实体表（有 name + type 字段的表）
    entity_table = None
    for t in tables:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
        if 'name' in cols and ('type' in cols or 'entity_type' in cols):
            entity_table = t
            break
    
    # 策略2：找事实/内容表（有 content 字段的表）
    fact_table = None
    for t in tables:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
        if 'content' in cols:
            fact_table = t
            break
    
    # 策略3：自动映射字段
    # ...
    
    return {
        'entity_table': entity_table,
        'fact_table': fact_table,
        'field_map': auto_detect_fields(...)
    }
```

**效果：** 拿任何 SQLite 都能自动探测结构，不再要求固定 schema。真正实现 "point at a file, it just works"。

#### P0-2：Markdown 适配器加自动关联

**文件：** `adapters/markdown_adapter.py`

**方案：** 从 app.py 已验证的关键词关联逻辑移植过来：
1. 提取每个文件的标题+前5个 heading 的关键词（中文2字+，英文3字+）
2. 两个文件共享3+关键词 → 自动连边，label="关键词: xxx, yyy"
3. 从 YAML frontmatter 提取 tags，共享 tag 也连边

**效果：** 没有手动 wikilinks 的文件夹也能看到密集的关系网络。

#### P0-3：README 诚实化

**文件：** `README.md`

**修改点：**
- "Directly reads Hermes Agent fact_store" → "Auto-detects SQLite schema, tested with Hermes Agent fact_store"
- 加 "已知限制" 章节：说明当前关联策略是关键词重叠，不是语义向量
- 去掉 "Claude Code memory" 的明确支持声称（目前没验证过 Claude Code 的 schema）
- 加截图/演示 GIF（用户5秒内能看懂）

---

### 🟡 P1 — 本周改（提升可用性）

#### P1-1：前端节点详情面板

**文件：** `index.html`

**方案：** 点击节点时右侧弹出面板：
- 节点名称、类型、所属目录
- 关联的 fact 内容列表
- 直连节点列表（可点击跳转）
- 文件路径（如果有的话）

**技术：** 在 `index.html` 加一个 `.detail-panel` div，D3 点击事件填充内容。

#### P1-2：前端按边类型着色

**文件：** `index.html`

**方案：**
- wikilink 边 → 绿色虚线
- keyword 边 → 蓝色细线
- entity 边 → 橙色粗线
- 在 stats API 返回 edge_types 分布，前端渲染时根据 label 区分

#### P1-3：统计仪表板

**文件：** `index.html`

**方案：** 左下角固定显示：
- 总节点/边数
- 各类型节点占比（环形图）
- 孤立节点数（无连接的节点）
- 最密集连接的 TOP 5 节点

#### P1-4：配置文件示例更新

**文件：** `config.yaml.example`

**方案：** 加完整的配置示例，包含：
- schema 自定义映射（不需要自动探测时）
- 关键词关联的阈值配置
- 认证配置
- 多数据源配置

---

### 🟢 P2 — 以后改（锦上添花）

#### P2-1：语义向量关联（QMD 集成）

**方案：** 新增 `adapters/qmd_adapter.py`
- 调用 QMD 的向量搜索 API
- 对每个文件找语义最近的 3 个文件，自动连边
- 这是最理想的关联方式，但需要 QMD 服务

#### P2-2：时间线视图

**方案：** 从文件修改时间或 YAML frontmatter 的 date 字段提取时间，加一个时间轴滑块。

#### P2-3：布局算法切换

**方案：** 支持力导向（当前）、层次布局、环形布局切换。

#### P2-4：多语言 UI

**方案：** 前端加 i18n，支持中英文切换。

---

## 三、执行顺序

```
第1步：P0-1 + P0-2 + P0-3（核心能力 + README）→ v1.1 release
第2步：P1-1 + P1-2 + P1-3（前端增强）→ v1.2 release
第3步：P2-1（语义关联）→ v2.0 release
```

## 四、成功标准

| 指标 | 当前 | 目标 |
|------|------|------|
| 用户拿到手5分钟内能看到效果 | ❌ 需要特定 schema | ✅ 任何 SQLite/MD 都能跑 |
| 没有手动 wikilinks 也有边 | ❌ 几乎没边 | ✅ 关键词自动关联 |
| README 描述与实际能力一致 | ❌ 过度宣传 | ✅ 诚实准确 |
| 前端能看到节点内容 | ❌ 只能看到名字 | ✅ 详情面板 |
