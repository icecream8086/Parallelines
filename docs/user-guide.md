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

Parallelines 是一款 Source 1 引擎 VPK/addon 资源依赖分析工具。通过虚拟文件系统（VFS）叠加模型解析游戏文件的优先级裁决，通过 NetworkX 依赖图追踪文件引用关系，最终通过可插拔分析器输出冗余、死文件、冲突和依赖断裂报告。

### 支持的游戏

| 游戏 | 状态 |
|------|------|
| Left 4 Dead 2 | 已验证 |
| Team Fortress 2 | 支持 |
| Portal / Portal 2 | 支持 |
| Half-Life 2 系列 | 支持 |
| CS:S / DoD:S | 支持 |

**不支持**：Source 2 游戏（CS2、Dota 2、Deadlock、HL:Alyx），Respawn 魔改 VPK（Titanfall），非 Source 引擎的 `.vpk` 文件。

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
python scripts/build_exe.py
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

**输出**: `store.files`（`is_redundant` 字段）

### DeadFile（死文件分析）

多源 BFS 从入口点集合出发在依赖图中遍历，所有不可达文件标记为 `is_dead=True`。入口点包含 `.bsp` 地图、manifest 声景/粒子引用、全局脚本和 `gameinfo.txt`。

**限制**: 入口点覆盖不足时假阳性偏高。

**输出**: `store.files`（`is_dead` 字段）

### HashConflict（哈希冲突）

同一 `virtual_path` 在不同来源间文件内容不同（CRC/hash 不一致）。

**输出**: `store.hash_conflicts`（`virtual_path`, `winner_source`, `loser_source`, `winner_hash`, `loser_hash`）

### DependencyConflict（依赖断裂）

文件 A 引用 B，但 B 的实际提供者与预期来源不同（或 B 不存在）。

**输出**: `store.dep_conflicts`（`from_path`, `to_path`, `expected_source`, `actual_source`）

### IsolatedPackage（孤立包）

按 `source_name` 统计死文件和冗余文件数量。

**输出**: `store.isolated`（`source_name`, `dead_file_count`, `example_paths`）

### Impact（影响面分析）

统计每个文件在依赖图中被多少其他文件依赖。

**输出**: `store.impact`（`virtual_path`, `source_name`, `impact_count`）

---

## 5. JSON 查询引擎

查询引擎实现完整的关系代数管线：

```
JSON dict → Parser → AST → Validator → Optimizer → Executor → Relation
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

- 关系名：`files`, `dependencies`, `addons`, `hash_conflicts`, `dep_conflicts`, `isolated`, `impact`, `mod_types`, `entry_points`, `global_scripts`, `dependency_cycles`, `external_files`, `implicit_deps`, `cascade_overrides`
- 子查询：`{"query": {...}}`
- 图函数：`{"descendants_of": "path"}`, `{"ancestors_of": "path"}`, `{"find_cycles": true}`

### WHERE 谓词

| 类型 | JSON 格式 | 说明 |
|------|-----------|------|
| eq / neq | `{"eq": ["col", val]}` | 等值 / 不等值 |
| gt / gte / lt / lte | `{"gt": ["col", 10]}` | 数值比较 |
| like | `{"like": ["col", "*.vmt"]}` | fnmatch 通配（`*` / `?`，非 SQL `%`/`_`） |
| in / not_in | `{"in": ["col", [1,2,3]]}` | 集合包含 |
| is_null / is_not_null | `{"is_null": "col"}` | NULL 检查 |
| starts_with / ends_with | `{"starts_with": ["col", "pre"]}` | 字符串前后缀 |
| contains / not_contains | `{"contains": ["col", "sub"]}` | 子串匹配 |
| ancestor_is_map | `{"ancestor_is_map": "virtual_path"}` | 图：是否有 .bsp 祖先 |
| descendant_is_script | `{"descendant_is_script": "virtual_path"}` | 图：是否有 .nut 后代 |
| descendant_is_any | `{"descendant_is_any": {"column": "path", "params": {"exts": [".mdl"]}}}` | 图：后代是否包含指定扩展名 |
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

多表 JOIN 使用 `joins` 数组：

```json
{
  "joins": [
    {"type": "left", "with": "addons", "on": {"eq": [["files", "source_name"], ["addons", "addon_id"]]}},
    {"type": "left", "with": "external_files", "on": {"eq": [["files", "virtual_path"], ["external_files", "virtual_path"]]}}
  ]
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
{ "having": {"gte": ["total", 10]} }
```

### 图遍历

```json
{
  "select": ["source_name"],
  "from": {"descendants_of": "maps/c1m1_hotel.bsp"},
  "group_by": {"by": ["source_name"], "agg": {"cnt": "count"}}
}
```

---

## 6. 预置查询目录

`queries/` 目录包含 34 个开箱即用的 JSON 查询脚本。完整列表见 [`queries/README.md`](../queries/README.md)。

### 诊断类

| 预置名 | 回答的问题 |
|--------|-----------|
| `file_count_by_source` | 每个 VPK/addon 有多少文件？ |
| `dead_files` | 哪些 addon 文件不可达？ |
| `dead_by_source` | 哪个包的不可达文件最多？ |
| `redundant_by_source` | 哪个包的文件被覆盖最多？ |
| `entry_point_types` | 入口点类型分布？ |
| `active_vmt_files` | 当前生效的 .vmt 材质有哪些？ |
| `complete_dead_by_type` | 按来源类型统计死文件数量？ |
| `map_soundscape_coverage` | 哪些地图有对应音景文件？ |

### 冲突类

| 预置名 | 回答的问题 |
|--------|-----------|
| `hash_conflicts` | 同名文件哈希不一致？ |
| `missing_deps` | 引用目标文件不存在？ |
| `dep_conflicts_cross_source` | 跨 addon 依赖可能断裂？ |
| `cascade_overrides` | 文件被多来源级联覆盖？ |

### 包分析

| 预置名 | 回答的问题 |
|--------|-----------|
| `isolated_packages` | 哪些 addon 有不可达文件？ |
| `safe_to_delete` | 哪些 addon 可以安全删除？ |
| `mod_type_summary` | 各类型 Mod 数量和文件分布？ |
| `disabled_addons` | 哪些禁用 addon 占用磁盘？ |
| `implicit_deps` | 哪些 addon 隐式依赖其他 addon？ |
| `script_mods` | 哪些 addon 包含全局 .nut 脚本？ |

### 风险评估

| 预置名 | 回答的问题 |
|--------|-----------|
| `top_impact` | 被最多文件依赖的文件？ |
| `global_scripts` | 哪些全局脚本影响所有地图？ |
| `dependency_cycles` | 依赖图中是否有环路？ |
| `cross_map_pollution` | 哪些 addon 被多个地图共享？ |

### 资源追踪

| 预置名 | 回答的问题 |
|--------|-----------|
| `map_descendants` | 地图依赖了哪些 addon 的文件？ |
| `sound_chain` | 音效依赖链：哪些文件引用了 .wav？ |
| `infected_model_usage` | 感染者模型引用链？ |
| `melee_weapon_chain` | 近战武器引用链？ |
| `particle_coverage` | .pcf 粒子引用了哪些材质？ |
| `ui_texture_usage` | .res UI 文件引用了哪些纹理？ |
| `map_full_audio` | 每个地图引用了哪些音效？ |

### 外部 VPK

| 预置名 | 回答的问题 |
|--------|-----------|
| `external_overlap` | 外部 VPK 与当前环境路径交集？ |
| `external_overrides` | 外部 VPK 会覆盖哪些当前文件？ |
| `external_overridden` | 外部 VPK 会被哪些当前文件覆盖？ |
| `external_new_files` | 外部 VPK 中有哪些全新文件？ |
| `addon_full_profile` | 每个文件的包名 + 外部 VPK 状态全景？ |

### 使用

```bash
# 列出全部 34 个预置
python -m parallelines --list-presets

# 运行预置查询
python -m parallelines --game l4d2 --game-root "..." --analyze --query dead_by_source
```

---

## 7. 外部 VPK 分析

下载新 VPK 后，安装前评估影响：

```bash
python -m parallelines --game l4d2 --external "Downloads/pesaro.vpk"
```

自动执行三个分类查询：
- **OVERRIDES**: 外部 VPK 优先级更高且哈希不同 → 安装后会替换当前文件
- **OVERRIDDEN**: 当前文件优先级更高 → 外部文件不会生效
- **NEW FILES**: 当前环境中不存在的全新文件

---

## 8. SSD 缓存

首次分析后在 `./cache/` 生成缓存文件：

```
cache/
├── meta.json
├── all_files.parquet
└── dependencies.parquet
```

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

分析完成后进入交互提示符，`ResultStore` 常驻内存。

```
l4d2> {"select":["*"],"from":"hash_conflicts","limit":5}
+------+-------------------+------+
| ...  |                   |      |
+------+-------------------+------+
5 rows

l4d2> .tables
Available relations:
  files
  dependencies
  addons
  hash_conflicts
  dep_conflicts
  ...

l4d2> .schema hash_conflicts
Table: hash_conflicts
Columns: virtual_path, winner_source, loser_source, winner_hash, loser_hash

l4d2> .exit
```

### 元命令

| 命令 | 说明 |
|------|------|
| `.help` | 命令列表 |
| `.tables` | 可用 Relation 列表 |
| `.schema <t>` | 查看表结构 |
| `.mode <table/vertical/json/csv>` | 输出格式 |
| `.pager <on/off>` | 分页切换 |
| `.print <on/off>` | 自动打印结果 |
| `.echo <on/off>` | 查询回显（调试用） |
| `.save <file>` | 保存 store 到 JSON |
| `.load <file>` | 从 JSON 恢复 store |
| `.external <vpk>` | 加载外部 VPK |
| `.unload <ref>` | 移除外部 VPK 引用 |
| `.analyze` | 重新运行全量分析 |
| `.stores` | 列出活跃 store |
| `.history` | 命令历史 |
| `.exit` / `.quit` | 退出 |

---

## 10. 输出格式

| 格式 | 参数 | 说明 |
|------|------|------|
| JSON | `--format json` | 完整结构化报告 |
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

### 查询

| 选项 | 说明 |
|------|------|
| `--query <SPEC>` | 预置名或内联 JSON DSL |
| `--list-presets` | 列出预置查询 |

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
