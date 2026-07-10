# Parallelines 预置查询脚本库

> 26 个纯 JSON 查询脚本，通过 `--query` 运行。不需 Python 代码，编译为 EXE 后同样可用。
> 引擎版本：v2（支持多列 JOIN、θ-连接、图遍历源、跨列比较、条件聚合、多表 JOIN）

## 使用方式

```bash
# 列出所有预设
parallelines --list-presets

# 分析 + 运行预设查询
parallelines --game l4d2 --game-root "..." --analyze --query dead_by_source

# 分析外部 VPK + 外部覆盖检测
parallelines --game l4d2 --game-root "..." --external pesaro.vpk --query external_overrides

# 分析外部 VPK + 多表全景档案（需先加载外部引用）
parallelines --game l4d2 --game-root "..." --external pesaro.vpk --query addon_full_profile

# 图遍历：查找地图的所有下游文件
parallelines ... --analyze --query map_descendants

# 内联 JSON DSL（高级用法）
parallelines ... --analyze --query '{"select":["source_type","cnt"],"from":"files","group_by":{"by":["source_type"],"agg":{"cnt":"count"}}}'

# 跳过冷启动确认（脚本/CI 用）
parallelines ... --analyze --query dead_files --yes
```

## 查询索引

### 诊断类 — 快速了解全局

| 文件 | 回答的问题 | 要点 |
|------|-----------|------|
| `file_count_by_source.json` | 每个 VPK/addon 有多少文件？ | GROUP BY + COUNT |
| `dead_files.json` | 哪些 addon 文件不可达？ | AND 复合谓词 |
| `dead_by_source.json` | 哪个包的不可达文件最多？ | GROUP BY + WHERE |
| `redundant_by_source.json` | 哪个包的文件被覆盖最多？ | GROUP BY + WHERE |
| `entry_point_types.json` | 入口点的类型分布？ | 直接查询 entry_points |
| `active_vmt_files.json` | 当前生效的 .vmt 材质有哪些？ | `like` 通配符模式匹配 |

### 冲突类 — 定位具体问题

| 文件 | 回答的问题 | 要点 |
|------|-----------|------|
| `hash_conflicts.json` | 哪些同名文件哈希不一致？ | 直接查询 hash_conflicts |
| `missing_deps.json` | 哪些引用的目标文件不存在？ | `eq` 过滤 actual_source |
| `dep_conflicts_cross_source.json` | 哪些跨 addon 依赖可能断裂？ | `neq` 过滤 MISSING |
| `cascade_overrides.json` | 哪些文件被 3+ 来源级联覆盖？ | 直接查询 cascade_overrides |

### 包分析类 — 定位有问题的 addon

| 文件 | 回答的问题 | 要点 |
|------|-----------|------|
| `isolated_packages.json` | 哪些 addon 有不可达文件？ | `gt` 数值比较 |
| `safe_to_delete.json` | 哪些 addon 可以安全删除？ | **v2**: `count_where` 条件聚合 + `having` |
| `mod_type_summary.json` | 各类型 Mod 的数量和文件分布？ | 多列聚合（sum） |
| `disabled_addons.json` | 哪些禁用 addon 占用磁盘？ | 直接查询 mod_types |
| `implicit_deps.json` | 哪些 addon 隐式依赖其他 addon？ | 直接查询 implicit_deps |
| `script_mods.json` | 哪些 addon 包含全局 .nut 脚本？ | **v2**: `ends_with` + `not_contains` 字符串谓词 |

### 风险类 — 评估修改影响

| 文件 | 回答的问题 | 要点 |
|------|-----------|------|
| `top_impact.json` | 哪些文件被最多文件依赖？ | ORDER BY DESC |
| `global_scripts.json` | 哪些全局脚本影响所有地图？ | 直接查询 global_scripts |
| `dependency_cycles.json` | 依赖图中是否有环路？ | `find_cycles` 图源 |
| `cross_map_pollution.json` | 哪些 addon 被多个地图共享？ | **v2**: `ancestor_is_map` 图谓词 + `having` |

### 图遍历类 — v2 新增

| 文件 | 回答的问题 | 要点 |
|------|-----------|------|
| `map_descendants.json` | 一个地图依赖了哪些 addon 的文件？ | **v2**: `descendants_of` 图源，按来源分组统计 |

### S9 外部 VPK

| 文件 | 回答的问题 | 要点 |
|------|-----------|------|
| `external_overlap.json` | 外部 VPK 与当前环境的路径交集？ | **v2**: 跨列 JOIN（列名前缀限定） |
| `external_overrides.json` | 外部 VPK 会覆盖哪些当前文件？ | **v2**: 跨列 `gt` 比较 |
| `external_overridden.json` | 外部 VPK 的哪些文件会被当前覆盖？ | **v2**: 跨列 `lt` 比较 |
| `external_new_files.json` | 外部 VPK 有哪些当前环境不存在的文件？ | **v2**: `not_exists_in` 跨关系谓词 |

### 多表 JOIN 类 — v2 新增

| 文件 | 回答的问题 | 要点 |
|------|-----------|------|
| `addon_full_profile.json` | 每个文件的包名 + 外部 VPK 状态？ | **v2**: 3 表 LEFT JOIN（`joins` 数组） |

---

## v2 引擎能力速查

v2 引擎在标准 JSON DSL 基础上新增以下能力，全部可在 `.json` 查询脚本中直接使用：

### 新增谓词

| 谓词 | JSON 语法 | 用途 |
|------|-----------|------|
| `starts_with` | `{"starts_with": ["col", "prefix"]}` | 路径前缀过滤 |
| `ends_with` | `{"ends_with": ["col", ".nut"]}` | 扩展名过滤 |
| `contains` | `{"contains": ["col", "substr"]}` | 子串匹配 |
| `not_contains` | `{"not_contains": ["col", "maps/"]}` | 排除路径模式 |
| `not_in` | `{"not_in": ["col", ["a","b"]]}` | 排除特定值 |
| `exists_in` | `{"exists_in": ["col", "relation"]}` | 跨关系存在检查 |
| `not_exists_in` | `{"not_exists_in": ["col", "relation"]}` | 跨关系缺失检查 |
| `ancestor_is_map` | `{"ancestor_is_map": ["col"]}` | 图：检查文件是否有 .bsp 祖先 |
| `descendant_is_script` | `{"descendant_is_script": ["col"]}` | 图：检查文件是否有 .nut 后代 |

### 新增源类型

| 源 | JSON 语法 | 说明 |
|----|-----------|------|
| `descendants_of` | `{"from": {"descendants_of": "path"}}` | 图中某节点的所有下游可达节点 |
| `ancestors_of` | `{"from": {"ancestors_of": "path"}}` | 图中某节点的所有上游节点 |
| `find_cycles` | `{"from": {"find_cycles": true}}` | 依赖图中的环路检测 |

### 新增聚合能力

| 能力 | JSON 语法 | 用途 |
|------|-----------|------|
| `count_where` | `{"count_where": {"eq": ["col", val]}}` | 条件计数（替代 WHERE + COUNT 的两步操作） |
| `having` | `"having": {"gte": ["agg_col", N]}` | 聚合后过滤（与 SQL HAVING 等价） |
| 多列聚合 | `"agg": {"total": "count", "size": ["sum", "file_size"]}` | 同时计算多个聚合函数 |

### 新增 JOIN 能力

| 能力 | JSON 语法 | 说明 |
|------|-----------|------|
| 多列等值 | `"on": {"and": [{"eq": ["a","b"]}, {"eq": ["c","d"]}]}` | 复合主键连接 |
| 跨列比较 | `"where": {"gt": [["R", "col1"], ["S", "col2"]]}` | 不等值跨列比较（`gt/lt/gte/lte`） |
| 多表 JOIN | `"joins": [{...}, {...}]` | 3+ 表链式连接 |
| 列名前缀限定 | `["files", "virtual_path"]` | 消除多表 JOIN 中的列歧义 |

---

## 自定义查询

复制任意 `.json` 文件修改 `select`/`where`/`group_by`/`joins` 等字段，用 `--query` 指定文件路径：

```bash
parallelines ... --analyze --query path/to/my_query.json
```

也支持内联 JSON：

```bash
# 单表查询
parallelines ... --analyze --query '{"select":["*"],"from":"hash_conflicts","limit":50}'

# 多表 JOIN（v2）
parallelines ... --analyze --query '{"select":["*"],"from":"files","joins":[{"type":"left","with":"addons","on":{"eq":["source_name",["addons","addon_id"]]}}],"limit":50}'

# 图遍历（v2）
parallelines ... --analyze --query '{"select":["source_name","file_count"],"from":{"descendants_of":"maps/c1m1.bsp"},"group_by":{"by":["source_name"],"agg":{"file_count":"count"}},"limit":20}'
```

## 文件清单（26 个）

```
active_vmt_files.json          hash_conflicts.json
addon_full_profile.json        implicit_deps.json
cascade_overrides.json         isolated_packages.json
cross_map_pollution.json       map_descendants.json
dead_by_source.json            missing_deps.json
dead_files.json                mod_type_summary.json
dep_conflicts_cross_source.json redundant_by_source.json
dependency_cycles.json         safe_to_delete.json
disabled_addons.json           script_mods.json
entry_point_types.json         top_impact.json
external_new_files.json
external_overlap.json
external_overridden.json
external_overrides.json
file_count_by_source.json
global_scripts.json
```
