<div align="center">

# 🧠 BrainGraph

**Knowledge Graph Visualizer for AI Memory & More**

Turn your AI agent's memory, wiki, or any structured data into a beautiful interactive knowledge graph.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

---

## ✨ Features

- 🤖 **AI Memory Viz** — Directly reads Hermes Agent fact_store / Claude Code memory
- 📝 **Wiki Graph** — Auto-generates graph from Markdown `[[links]]`
- 📓 **Obsidian Compatible** — Drop your vault, get a web-based graph view
- ⚡ **Zero Config** — Point at a file/folder, it just works
- 🎨 **Beautiful UI** — Dark/light themes, smooth animations
- 🔎 **Interactive** — Search, filter, local graph (depth 1-3), zoom, detail panel
- 📸 **Export** — Save any view as PNG
- 🐳 **Docker Ready** — One command deploy
- 🔌 **Pluggable** — Write your own data adapter in 50 lines

## 🚀 Quick Start

### Option 1: Clone & Run
```bash
git clone https://github.com/whygj/brain-graph
cd brain-graph
pip install flask pyyaml
python app.py --source ~/.hermes/memory_store.db
```

### Option 2: Docker
```bash
docker build -t brain-graph .
docker run -p 9121:9121 -v ~/.hermes:/data:ro brain-graph
```

Open **http://localhost:9121** — that's it.

### Auto-detect
If you have Hermes Agent installed, just run without arguments:
```bash
python app.py
```
It will auto-detect `~/.hermes/memory_store.db`.

## 📖 Use Cases

| Who | What |
|-----|------|
| **Hermes Agent users** | Visualize your agent's entire memory store |
| **Claude Code users** | Export and explore your AI's knowledge |
| **Obsidian users** | Web-based graph view, no Electron needed |
| **Knowledge workers** | Turn any structured data into a graph |
| **Teams** | Share a live visualization of your knowledge base |

## ⚙️ Configuration

Copy `config.yaml.example` to `config.yaml`:

```yaml
server:
  port: 9121

sources:
  - name: "AI Memory"
    type: "sqlite"
    path: "~/.hermes/memory_store.db"

  - name: "My Wiki"
    type: "markdown"
    path: "~/wiki"

  - name: "Obsidian Vault"
    type: "obsidian"
    path: "~/my-vault"

# Optional password
# auth:
#   password: "your-password"
```

Then: `python app.py`

## 🔌 Adapters

| Adapter | Input | Auto-detect |
|---------|-------|-------------|
| `sqlite` | SQLite DB (Hermes fact_store format) | `.db` / `.sqlite` files |
| `markdown` | Folder of `.md` files with `[[links]]` | folders with .md files |
| `obsidian` | Obsidian vault folder | folders with `.obsidian/` |
| `json` | JSON `{nodes, edges}` or flat array | `.json` files |

### Writing a Custom Adapter

```python
# adapters/my_adapter.py
class MyAdapter:
    source_type = "custom"

    def __init__(self, config):
        self._nodes = [{"id": "hello", "type": "demo", "facts": 1}]
        self._edges = []
        self._entity_facts = {}
        self._stats = {"total_nodes": 1, "total_edges": 0}

    @property
    def nodes(self): return self._nodes
    @property
    def edges(self): return self._edges
    @property
    def entity_facts(self): return self._entity_facts
    @property
    def stats(self): return self._stats
```

Register it in `adapters/__init__.py` and add the type to `config.yaml`.

## 🛠 API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Frontend |
| `GET /api/graph-data` | Full graph data (nodes + edges + facts) |
| `GET /api/graph-data?source=Wiki` | Graph from a specific source |
| `GET /api/sources` | List configured data sources |
| `GET /api/stats` | Statistics |
| `GET /api/search?q=keyword` | Search nodes and facts |

## 🎯 Why BrainGraph?

**Obsidian** requires you to manually create `[[links]]`. **Neo4j** needs a dedicated database. **Gephi** is a heavy desktop app.

BrainGraph is different:
- **Zero manual work** — extracts graph structure from your existing data
- **Zero dependencies** — no database, no build step, no npm
- **Single command** — `python app.py --source your-data`
- **AI-first** — built for the Agent era where AI memory matters

## 🤝 Contributing

PRs welcome! Especially:
- New adapters (Notion, Roam, Logseq, Joplin, etc.)
- Layout algorithms (hierarchical, radial, circular)
- Theme contributions
- Bug fixes and translations

## 📄 License

MIT © 2026 AgentMJ

---

<div align="center">

# 🧠 BrainGraph 中文说明

**AI记忆与知识图谱可视化工具**

</div>

### 特色

- 🤖 直接读取 Hermes Agent 的 fact_store 记忆库
- 📝 自动从 Markdown 的 `[[链接]]` 生成图谱
- 📓 兼容 Obsidian vault，Web 版图谱无需 Electron
- ⚡ 零配置 — 指向文件或文件夹，自动识别数据格式
- 🎨 暗色/亮色主题切换，动画流畅
- 🔎 交互式 — 搜索、过滤、局部图、缩放、详情面板
- 📸 一键导出 PNG 截图
- 🐳 Docker 一键部署

### 快速开始

```bash
git clone https://github.com/whygj/brain-graph
cd brain-graph
pip install flask pyyaml
python app.py --source ~/.hermes/memory_store.db
```

打开 http://localhost:9121 即可看到你的知识图谱。

### 为什么做这个？

Obsidian 的图谱视图需要你手动创建 `[[链接]]`。
BrainGraph 不需要任何额外工作——直接从已有数据自动生成图谱。

AI Agent 用户（Hermes、Claude Code）有大量记忆数据但看不到。
BrainGraph 让你一目了然：AI 知道了什么，哪些知识是连通的，哪些是孤立的。

### 适用场景

- Hermes Agent 用户 → 可视化 fact_store 记忆库
- Claude Code 用户 → 导出记忆后探索
- Obsidian 用户 → 更好的 Web 版图谱
- 知识工作者 → 任意结构化数据可视化
