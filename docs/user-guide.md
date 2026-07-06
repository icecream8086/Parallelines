# Parallelines 用户手册

> 版本 0.1.0 | 2026-07

## 目录

1. [概述](#1-概述)
2. [安装](#2-安装)
3. [快速入门](#3-快速入门)
4. [分析器详解](#4-分析器详解)
5. [JSON 查询引擎](#5-json-查询引擎)
6. [预置查询目录](#6-预置查询目录)
7. [外部 VPK 分析](#7-外部-vpk-分析)
8. [SSD 缓存](#8-ssd-缓存)
9. [REPL 交互模式](#9-repl-交互模式)
10. [输出格式](#10-输出格式)
11. [CLI 完整参考](#11-cli-完整参考)

---

## 1. 概述

Parallelines 是一款 Source 引擎 VPK/addon 资源依赖分析工具。它通过虚拟文件系统（VFS）叠加模型解析游戏文件的优先级裁决结果，通过 NetworkX 依赖图追踪文件引用关系，最终通过 6 个可插拔分析器输出冗余、死文件、冲突和依赖断裂报告。

### 支持的游戏

| 游戏 | 状态 |
|------|------|
| Left 4 Dead 2 | 已验证（81,955 文件, 162 addon 实测） |
| CS:GO, TF2, Portal 2, Dota 2, Half-Life 2 系列 | 占位支持 |
| Source SDK / 通用 | 占位支持 |

**不支持**：Respawn 魔改 VPK（Titanfall）、非 Source 引擎的 `.vpk` 文件。

---

## 2. 安装

### 开发环境

```bash
git clone <repo-url> && cd Parallelines
conda create -n parallelines python=3.11 -y
conda activate parallelines
pip install -e ".[dev]"
```

### 验证

```bash
python -m parallelines --help
python -m parallelines --version
pytest
```

### 构建独立 EXE

```bash
pip install "parallelines[build]"
python scripts/build_exe.py           # 完整版 (~160MB)
python scripts/build_exe.py --minimal  # 精简版 (~40MB, 无缓存)
```

产物位于 `dist/parallelines/`。

---

## 3. 快速入门

```bash
# 基础分析
python -m parallelines --game l4d2 \
  --game-root "/path/to/left4dead2" \
  --analyze

# 指定地图入口点
python -m parallelines --game l4d2 --analyze \
  --maps c1m1_hotel c2m1_highway

# 运行预置查询
python -m parallelines --game l4d2 --query dead_by_source

# 内联 JSON 查询
python -m parallelines --game l4d2 --query \
  '{"select":["source_name"],"from":"files","where":{"ends_with":["virtual_path",".nut"]},"limit":10}'
```

---

## 4. 分析器详解

### Redundancy（冗余分析）

检测被更高优先级来源覆盖的文件。每个 `virtual_path` 在 VFS 中可能由多个来源提供，只有最高优先级的生效版本为 `is_active=True`，其余标记为 `is_redundant=True`。

**输出关系**: `store.files`（通过 `is_redundant` 字段）

### DeadFile（死文件分析）

多源 BFS 从入口点集合出发在依赖图中遍历，所有不可达文件标记为 `is_dead=True`。入口点包含地图 `.bsp`、manifest 中的声景/粒子引用、全局脚本和 `gameinfo.txt`。

**限制**: 需确保入口点覆盖充分，否则误报（假阳性）偏高。

**输出关系**: `store.files`（通过 `is_dead` 字段）

### HashConflict（哈希冲突）

同一 `virtual_path` 在不同来源间文件内容不同（CRC/hash 不一致）。真正的 mod 冲突——同名文件但实际内容不同。

**输出关系**: `store.hash_conflicts`（列: `virtual_path`, `winner_source`, `loser_source`, `winner_hash`, `loser_hash`）

### DependencyConflict（依赖断裂）

文件 A 引用 B，但 B 的实际提供者与 A 的预期来源不同（或 B 不存在）。跨 addon 隐式依赖断裂的主要原因。

**输出关系**: `store.dep_conflicts`（列: `from_path`, `to_path`, `expected_source`, `actual_source`）

### IsolatedPackage（孤立包）

按 `source_name` 统计死文件和冗余文件数量。`dead_file_count == total_files` 的包完全孤立，可安全删除。

**输出关系**: `store.isolated`（列: `source_name`, `total_files`, `dead_file_count`, `redundant_file_count`）

### Impact（影响面分析）

统计每个文件在依赖图中作为前驱被多少其他文件依赖。Top 20 为关键枢纽文件——修改或删除它们影响面最广。

**输出关系**: `store.impact`（列: `virtual_path`, `impact_count`）

---

## 5. JSON 查询引擎

查询引擎实现完整的关系代数管线：

```
JSON dict → Parser → AST → Validator → Executor → Relation
```

### 查询结构

```json
{
  "select": ["col1", ["rel", "col2"]],
  "from": "files",
  "where": { "and": [ ... ] },
  "join": { "type": "inner", "with": "other", "on": { ... } },
  "group_by": { "by": ["col"], "agg": { "alias": "agg_fn" } },
  "having": { "gt": ["alias", 10] },
  "order_by": { "by": "col", "dir": "desc" },
  "limit": 100
}
```

### SELECT / FROM

必须字段。`select` 为列名数组，`"*"` 表示全列。`from` 为以下之一：

- 关系名：`files`, `hash_conflicts`, `dep_conflicts`, `impact`, `isolated`, `mod_types`, `entry_points`, `global_scripts`, `dependency_cycles`, `external_files`, `implicit_deps`, `cascade_overrides`
- 子查询：`{"query": {...}}`
- 图函数：`{"descendants_of": "path"}`, `{"ancestors_of": "path"}`, `{"find_cycles": true}`

### WHERE 谓词

| 类型 | JSON 格式 | 说明 |
|------|-----------|------|
| eq / neq | `{"eq": ["col", val]}` | 等值 / 不等值 |
| gt / gte / lt / lte | `{"gt": ["col", 10]}` | 数值比较 |
| like | `{"like": ["col", "*.vmt"]}` | fnmatch 通配 |
| in / not_in | `{"in": ["col", [1,2,3]]}` | 集合包含 |
| is_null / is_not_null | `{"is_null": "col"}` | NULL 检查 |
| starts_with / ends_with | `{"starts_with": ["col", "pre"]}` | 字符串前后缀 |
| contains / not_contains | `{"contains": ["col", "sub"]}` | 子串匹配 |
| ancestor_is_map | `{"ancestor_is_map": "virtual_path"}` | 图：是否有 .bsp 祖先 |
| descendant_is_script | `{"descendant_is_script": "virtual_path"}` | 图：是否有 .nut 后代 |
| exists_in / not_exists_in | `{"exists_in": ["col", "relation"]}` | 跨表存在性 |
| and / or / not | `{"and": [p1, p2]}` | 逻辑复合 |

### JOIN

支持 inner / left / right / full 四种类型，ON 条件支持等值和跨列比较：

```json
{
  "join": {
    "type": "inner",
    "with": "files",
    "on": {"eq": [["external_files", "virtual_path"], ["files", "virtual_path"]]}
  }
}
```

### GROUP BY / 聚合

```json
{
  "group_by": {
    "by": ["source_name"],
    "agg": {
      "total": "count",
      "total_size": ["sum", "file_size"],
      "avg_size": ["avg", "file_size"],
      "active": {"count_where": {"eq": ["is_active", true]}}
    }
  }
}
```

支持的聚合：`count`, `sum`, `avg`, `min`, `max`, `count_where`

### HAVING

聚合后过滤，在 GROUP BY 之后执行：

```json
{ "having": {"gt": ["total", 10]} }
```

### 图遍历

```json
// 从地图出发的所有下游文件按 VPK 分组
{
  "select": ["source_name"],
  "from": {"descendants_of": "maps/c1m1_hotel.bsp"},
  "group_by": {"by": ["source_name"], "agg": {"cnt": "count"}}
}

// 筛选有 .bsp 祖先的文件
{
  "select": ["virtual_path"],
  "from": "files",
  "where": {"ancestor_is_map": "virtual_path"}
}
```

---

## 6. 预置查询目录

`queries/` 目录包含 21 个开箱即用的 JSON 查询脚本。

### 诊断类

| 预置名 | 回答的问题 |
|--------|-----------|
| `file_count_by_source` | 每个 VPK/addon 有多少文件？ |
| `dead_files` | 哪些 addon 文件不可达？ |
| `dead_by_source` | 哪个包的不可达文件最多？ |
| `redundant_by_source` | 哪个包的文件被覆盖最多？ |
| `entry_point_types` | 入口点类型分布？ |
| `active_vmt_files` | 当前生效的 .vmt 材质有哪些？ |

### 冲突类

| 预置名 | 回答的问题 |
|--------|-----------|
| `hash_conflicts` | 同名文件哈希不一致？ |
| `missing_deps` | 引用目标文件不存在？ |
| `dep_conflicts_cross_source` | 跨 addon 依赖可能断裂？ |
| `cascade_overrides` | 文件被 3+ 来源级联覆盖？ |

### 包分析

| 预置名 | 回答的问题 |
|--------|-----------|
| `isolated_packages` | 哪些 addon 有不可达文件？ |
| `mod_type_summary` | 各类型 Mod 数量和文件分布？ |
| `disabled_addons` | 哪些禁用 addon 占用磁盘？ |
| `implicit_deps` | 哪些 addon 隐式依赖其他 addon？ |

### 风险评估

| 预置名 | 回答的问题 |
|--------|-----------|
| `top_impact` | 被最多文件依赖的文件？ |
| `global_scripts` | 哪些全局脚本影响所有地图？ |
| `dependency_cycles` | 依赖图中是否有环路？ |

### 外部 VPK

| 预置名 | 回答的问题 |
|--------|-----------|
| `external_overlap` | 外部 VPK 与当前环境路径交集？ |
| `external_overrides` | 外部 VPK 会覆盖哪些当前文件？ |
| `external_overridden` | 外部 VPK 会被哪些当前文件覆盖？ |
| `external_new_files` | 外部 VPK 中有哪些全新文件？ |

---

## 7. 外部 VPK 分析

下载新 VPK 后，安装前评估影响：

```bash
python -m parallelines --game l4d2 --external "Downloads/pesaro.vpk"
```

自动执行三个分类查询：
- **OVERRIDES**: 外部 VPK 优先级更高且哈希不同→安装后会替换当前文件
- **OVERRIDDEN**: 当前文件优先级更高→外部文件不会生效
- **NEW FILES**: 当前环境中不存在的全新文件

结果同时输出到控制台和 JSON 报告。

---

## 8. SSD 缓存

首次分析后自动在 `./cache/` 生成缓存文件：

```
cache/
├── meta.json           # 缓存元数据
├── all_files.parquet   # VFS 全量文件
└── dependencies.parquet # 已解析的依赖边
```

热缓存启动流程：Parquet 读取（~3MB, 2-5s）→ VFS 解析（1-2s）→ 依赖图缓存构建（1-3s）→ 分析器（10-50s）。总计 ~15-70s，对比冷启动 ~90-300s。

```bash
# 跳过缓存强制重建
python -m parallelines --game l4d2 --analyze --no-cache

# 清除旧缓存
python -m parallelines --game l4d2 --analyze --clean-cache
```

---

## 9. REPL 交互模式

```bash
python -m parallelines --game l4d2 --repl
```

分析完成后进入交互提示符，`ResultStore` 常驻内存，每次查询微秒级延迟。

```
l4d2> {"select":["*"],"from":"hash_conflicts","limit":5}
+------+-------------------+------+
| ...  |                   |      |
+------+-------------------+------+
5 rows in set (0.003s)

l4d2> .tables
Available relations (12):
  files          (123456 rows)
  dependencies   (104230 rows)
  ...

l4d2> .schema hash_conflicts
Table: hash_conflicts (1731 rows)
Columns (5):
  virtual_path, winner_source, loser_source, winner_hash, loser_hash

l4d2> .mode json
l4d2> dead_by_source
[{...}, ...]

l4d2> .exit
```

### 元命令

| 命令 | 说明 |
|------|------|
| `.help` | 命令列表 |
| `.tables` | 可用 Relation 列表 |
| `.schema <t>` | 查看表结构 |
| `.mode <table/vertical/json/csv>` | 输出格式 |
| `.pager <on/off>` | 分页（>50行默认开） |
| `.save <file>` | 保存 store 到 JSON |
| `.load <file>` | 从 JSON 恢复 store |
| `.external <vpk>` | 加载外部 VPK |
| `.analyze` | 重新运行全量分析 |
| `.history` | 命令历史 |
| `.exit` | 退出 |

---

## 10. 输出格式

| 格式 | 参数 | 说明 |
|------|------|------|
| JSON | `--format json` | 完整结构化报告，默认格式 |
| CSV | `--format csv` | 表格导入 |
| Text | `--format text` | 人类可读摘要 |
| HTML | `--format html` | 浏览器查看 |
| Graphviz | `--graphviz path.dot` | 依赖图可视化 |

---

## 11. CLI 完整参考

```
parallelines --game <ID> [--game-root <DIR>] [选项]
```

### 分析控制

| 选项 | 说明 |
|------|------|
| `--analyze` | 运行完整分析管线 |
| `--external <VPK>` | 外部 VPK 影响分析 |
| `--repl` | 交互式 REPL 模式 |
| `--maps <NAME...>` | 添加地图入口点 |
| `--entry-points <PATH...>` | 手动入口点路径 |
| `--compare-maps <VPK...>` | 地图版本比对 |

### 查询

| 选项 | 说明 |
|------|------|
| `--query <SPEC>` | 预置名或内联 JSON DSL |
| `--list-presets` | 列出 21 个预置查询 |

### 输出

| 选项 | 默认 | 说明 |
|------|------|------|
| `--format` | json | json / csv / text / html |
| `--output-dir` | ./reports | 输出目录 |
| `--graphviz <PATH>` | — | 输出 .dot 文件 |
| `--sv-pure <PATH>` | — | sv_pure 白名单 |

### 缓存

| 选项 | 说明 |
|------|------|
| `--no-cache` | 跳过缓存 |
| `--clean-cache` | 清除缓存后重建 |

### 资源

| 选项 | 默认 | 说明 |
|------|------|------|
| `--cpu <N>` | cpu_count-1 | Worker 数 |
| `--memory <SIZE>` | auto | 内存限制 |
| `--nolimit` | — | 无限制 |

### 日志

| 选项 | 说明 |
|------|------|
| `--log-level` | DEBUG / INFO / WARNING / ERROR |
| `--debug` | 完整 traceback |
| `--lang zh/en` | 界面语言 |
| `--yes` / `-y` | 跳过确认提示 |
