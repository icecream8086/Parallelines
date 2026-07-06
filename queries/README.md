# Parallelines 预置查询脚本库

> 18 个纯 JSON 查询脚本，通过 `--query` 运行。不需 Python 代码，编译为 EXE 后同样可用。

## 使用方式

```bash
# 列出所有预设
parallelines --list-presets

# 分析 + 运行预设查询
parallelines --game l4d2 --game-root "..." --analyze --query dead_by_source

# 分析外部 VPK + 查询
parallelines --game l4d2 --game-root "..." --external pesaro.vpk --query external_overlap

# 内联 JSON DSL（高级用法）
parallelines ... --analyze --query '{"select":["source_type","cnt"],"from":"files","group_by":{"by":["source_type"],"agg":{"cnt":"count"}}}'

# 跳过冷启动确认（脚本/CI 用）
parallelines ... --analyze --query dead_files --yes
```

## 查询索引

### 诊断类 — 快速了解全局

| 文件 | 回答的问题 |
|------|-----------|
| `file_count_by_source.json` | 每个 VPK/addon 有多少文件？ |
| `dead_files.json` | 哪些 addon 文件不可达？ |
| `dead_by_source.json` | 哪个包的不可达文件最多？ |
| `redundant_by_source.json` | 哪个包的文件被覆盖最多？ |
| `entry_point_types.json` | 入口点的类型分布？ |
| `active_vmt_files.json` | 当前生效的 .vmt 材质有哪些？ |

### 冲突类 — 定位具体问题

| 文件 | 回答的问题 |
|------|-----------|
| `hash_conflicts.json` | 哪些同名文件哈希不一致？ |
| `missing_deps.json` | 哪些引用的目标文件不存在？ |
| `dep_conflicts_cross_source.json` | 哪些跨 addon 依赖可能断裂？ |
| `cascade_overrides.json` | 哪些文件被 3+ 来源级联覆盖？ |

### 包分析类 — 定位有问题的 addon

| 文件 | 回答的问题 |
|------|-----------|
| `isolated_packages.json` | 哪些 addon 有不可达文件？ |
| `mod_type_summary.json` | 各类型 Mod 的数量和文件分布？ |
| `disabled_addons.json` | 哪些禁用 addon 占用磁盘？ |
| `implicit_deps.json` | 哪些 addon 隐式依赖其他 addon？ |

### 风险类 — 评估修改影响

| 文件 | 回答的问题 |
|------|-----------|
| `top_impact.json` | 哪些文件被最多文件依赖？ |
| `global_scripts.json` | 哪些全局脚本影响所有地图？ |
| `dependency_cycles.json` | 依赖图中是否有环路？ |

### S9 外部 VPK

| 文件 | 回答的问题 |
|------|-----------|
| `external_overlap.json` | 外部 VPK 与当前环境的路径交集？ |

> 精确的 override/overridden/new_files 分类需跨列比较，JSON DSL 不支持。用 `--external` 的预置查询：`--ref-query overrides`。

## 自定义查询

复制任意 `.json` 文件修改 `select`/`where`/`group_by` 等字段，用 `--query` 指定文件路径：

```bash
parallelines ... --analyze --query path/to/my_query.json
```

也支持内联 JSON：

```bash
parallelines ... --analyze --query '{"select":["*"],"from":"hash_conflicts","limit":50}'
```
