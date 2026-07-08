# Parallelines

Source 引擎 VPK/addon 资源依赖分析 CLI 工具。分析游戏资源的冗余、死文件、冲突与依赖断裂问题。

> **⚠️ 警告**：当前仅在 **L4D2 (Left 4 Dead 2)** 上完成完整测试。CS:GO、TF2、Portal 2、Dota 2 等其它 Source 引擎游戏支持为**理论兼容**，未经实际验证。

---

## 快速开始

```bash
conda activate parallelines
pip install -e ".[dev]"
python -m parallelines --help
```

### 分析 L4D2 游戏目录

```bash
python -m parallelines --game l4d2 \
  --game-root "D:/Steam/steamapps/common/Left 4 Dead 2/left4dead2" \
  --analyze
```

输出示例：

```
+--------------+--------+-------------+
| Analyzer     | Issues | Status      |
+--------------+--------+-------------+
| Redundancy   | 5983   | 5983 found  |
| DeadFile     | 75758  | 75758 found |
| HashConflict | 2299   | 2299 found  |
| DepConflict  | 92850  | 92850 found |
| Isolated     | 141    | 141 found   |
| Impact       | 20     | 20 found    |
+--------------+--------+-------------+
```

---

## 6 个分析器

| 分析器 | 检测内容 |
|--------|----------|
| **Redundancy** | 被高优先级来源覆盖的文件 |
| **DeadFile** | 从入口点出发无法到达的文件 |
| **HashConflict** | 同名但哈希不同的 addon 文件冲突 |
| **DependencyConflict** | 因覆盖导致引用来源断裂的依赖边 |
| **IsolatedPackage** | 全部文件不可达的孤立 addon |
| **Impact** | 被依赖次数最多的关键枢纽文件 |

---

## JSON 查询

```bash
# 预置查询
python -m parallelines --game l4d2 --query dead_by_source

# 内联 JSON DSL
python -m parallelines --game l4d2 --query \
  '{"select":["source_name"],"from":"files","where":{"ends_with":["virtual_path",".nut"]},"limit":10}'

# 图遍历
python -m parallelines --game l4d2 --query \
  '{"select":["source_name"],"from":{"descendants_of":"maps/c1m1_hotel.bsp"},"group_by":{"by":["source_name"],"agg":{"cnt":"count"}}}'

# 列出所有预置
python -m parallelines --list-presets
```

---

## 外部 VPK 分析

```bash
python -m parallelines --game l4d2 --external "Downloads/pesaro.vpk"
```

---

## REPL 交互模式

```bash
python -m parallelines --game l4d2 --repl
```

```
l4d2> {"select":["source_name"],"from":"files","limit":5}
+----------------+-------------+
| source_name    | source_type |
+----------------+-------------+
| 1621225890.vpk | vpk         |
+----------------+-------------+

l4d2> .tables                    # 列出所有 Relation
l4d2> .schema hash_conflicts     # 查看表结构
l4d2> .mode json                 # 切换输出格式
l4d2> .external pesaro.vpk       # 加载外部 VPK
l4d2> .save report.json          # 保存分析结果
l4d2> .exit
```

---

## 安装

### 开发环境

```bash
conda activate parallelines
pip install -e ".[dev]"
```

### 构建独立 EXE (Windows)

```bash
pip install "parallelines[build]"
python scripts/build_exe.py          # 完整版 ~160MB
python scripts/build_exe.py --minimal # 精简版 ~40MB
```

产物位于 `dist/parallelines/`，包含 `parallelines.exe` + `_internal/` 运行时。

---

## CLI 参考

```
parallelines --game <ID> --game-root <DIR> [选项]
```

### 必要参数

| 参数 | 说明 |
|------|------|
| `--game` | 游戏 ID：`l4d2`（已验证）、`csgo`、`tf2`、`portal2`、`dota2` 等 |
| `--game-root` | 包含 `gameinfo.txt` 的游戏目录 |

### 分析模式

| 参数 | 说明 |
|------|------|
| `--analyze` | 运行完整分析 |
| `--external <VPK>` | 分析外部 VPK 对当前环境的影响 |
| `--maps <NAME...>` | 指定地图入口点（提高死文件分析精度） |
| `--entry-points <PATH...>` | 手动指定入口点路径 |

### 查询引擎

| 参数 | 说明 |
|------|------|
| `--query <SPEC>` | 预置名或内联 JSON DSL |
| `--list-presets` | 列出所有预置查询 |

### 输出控制

| 参数 | 默认 | 说明 |
|------|------|------|
| `--format` | `json` | `json` / `csv` / `text` / `html` |
| `--output-dir` | `./reports` | 报告输出目录 |
| `--graphviz <PATH>` | — | 输出依赖图 `.dot` 文件 |

### 资源过滤

| 参数 | 过滤范围 |
|------|----------|
| `--check-textures` | `.vmt` / `.vtf` |
| `--check-models` | `.mdl` / `.vvd` / `.vtx` |
| `--check-sounds` | `.wav` / `.mp3` / `.ogg` |
| `--check-scripts` | `.nut` |
| `--check-all` | 全部 |

### 缓存与性能

| 参数 | 说明 |
|------|------|
| `--cpu <N>` | 并行 worker 数（0=无限制） |
| `--memory <SIZE>` | 内存限制，如 `4GB` |
| `--no-cache` | 跳过缓存，完整重建 |
| `--clean-cache` | 清除缓存后重建 |
| `--yes` / `-y` | 跳过冷启动确认提示 |

---

## 更多文档

- [用户手册 (docs/user-guide.md)](docs/user-guide.md)

---

## 许可证

MIT
