---
name: era5-wrf-pipeline
description: "区域 WRF 科研流水线：CDS/ERA5 下载、昆山曙光或其他 SLURM 超算上的 WPS/real/wrf 作业、wrfout 轻量提取和本地 matplotlib/cartopy 气象图。用于区域 WRF 模拟、ERA5 驱动、作业诊断和 wrfout 出图；在用户确认实验计划并配置站点环境后执行。"
---

# ERA5 WRF Pipeline

把 ERA5 驱动的区域 WRF 实验做成可复现、可诊断、可回传和可绘图的案例。所有实验必须由案例配置生成，不能把台风个例写死。

## 硬性边界

- 开工前必须完成需求澄清，并得到用户确认的《实验计划书》；未确认前不下载、不提交任何作业。按 `references/requirement-intake.md` 分四批提问，给选项和推荐默认值。
- 只读用户提供的参考材料；材料与用户要求冲突时报告差异并确认，不默认个人目录存在。
- 从用户私有站点配置读取 SSH 别名、账号、工作根、软件和地理数据路径；不要公开私有配置。生成给超算的脚本必须使用 Linux 路径。配置项见 `references/wrf-on-kunshan.md`。
- ERA5 只用 `cdsapi` 和用户已配置的 `~/.cdsapirc`；绝不读取、复制或回显 key、密码、token。
- 重计算全部通过 SLURM `sbatch`，禁止在登录节点前台运行 WPS、real 或 WRF。超算 Python 使用站点配置指定的解释器。
- ERA5 PLEV 和 SFC 分别在独立 `ungrib` 目录运行，使用 `Vtable.ERA-interim.pl`，再把中间文件链接回根目录执行 metgrid。若 metgrid 后三维变量（如 `TT`/`UU`/`VV`）变成二维，改用 `Vtable.ECMWF` 重跑 ungrib。
- **SST 陷阱必须处理**：ERA5 的海表温度在陆地上以 0 K 填充，在 15 km 及更细网格上会导致海岸线附近 2 m 气温接近 −273 °C。凡网格 ≤ 15 km 的沿海个例，提交前必须显式选择一种处理方式（移除 SST / 设 fill_missing / 陆海掩膜插值），见 `references/era5-input-pitfalls.md`。不得静默放过。
- 只用 `scp` 回传轻量提取结果和图片；绝不回传 8 GB 级原始 `wrfout`。
- 地图仅作科研示意时可用 Natural Earth；全国范围或需要国界合规时，必须改用符合国家标准的数据或在图注明确“边界仅供示意”，不得把 Natural Earth 边界冒充国界标准。**出图后必须确认国界实际绘制条数大于 0**——命中 0 条会被静默跳过，图上看不出报错。

## 工作流

### 阶段 -1：需求澄清

按 `references/requirement-intake.md` 分批提问：意图与用途、时空与配置、图型细节、交付与验收。每批结束后确认，答不上来就给 2–3 个选项并推荐默认值。发现“国际投稿但要求中文图”等矛盾时停下指出，不自行拍板。

把确认内容复述成计划书，至少包含：个例、UTC 起报和积分时长、区域、嵌套/分辨率、物理方案、ERA5 范围和图清单、语言、规格档位、验收标准、预计耗时。只有用户明确确认后进入阶段 0。

### 阶段 0：配置与一致性自检

在超算案例目录建立 `case.yaml`、`data/`、`wps/`、`wrf/`、`extract/`、`plots/`、`logs/`、`status/`。按 `references/case-config-guide.md` 生成 namelist 和 sbatch，不手改已生成文件。

先运行 `scripts/validate_case.py case.yaml`，检查网格整除和子域边界、配置时间窗、资料顶层覆盖及 time_step 经验上限。WPS 后填写实际层数，再加 `--metgrid-levels <实际值>` 核对。脚本不读取数据文件，也不证明实验设计有效；整个工作流仍须完成：

- `(e_we-1)`、`(e_sn-1)` 与嵌套比整除；
- 子域边界距父域边缘至少 5 格且不越界；
- `num_metgrid_levels`、`e_vert`、`p_top_requested` 与 ERA5 层数/资料顶层合理；
- 起止时间、`interval_seconds` 与下载时次一致；
- `time_step` 满足最外层网格约 6 倍原则，并记录保守值；
- 网格 ≤ 15 km 时，`driver.sst_handling` 已显式声明（否则告警，见 `references/era5-input-pitfalls.md`）。

另需人工核验（脚本覆盖不到）：ERA5 请求的 2D 变量清单完整、`LANDSEA` 存在、
三维变量确为三维、下载时次数与窗口匹配。这些都是“跑完不报错但结果错”的高发区。

### 阶段 1：ERA5、WPS、real、wrf

1. 在 `~/.cdsapirc` 已存在的前提下，用案例配置生成并提交 ERA5 PLEV/SFC 下载；请求带重试、目标文件存在且非空则跳过。
2. 通过配置的 SSH 别名建立案例目录，提交 WPS（geogrid → PLEV ungrib → SFC ungrib → metgrid）。
3. WPS 成功后提交 real，检查 `wrfinput_d01[/d02]` 和 `wrfbdy_d01` 存在。
4. 以 SLURM 依赖串联 `wrf`：`--dependency=afterok:<real_jobid>`；记录所有 jobid、提交命令、时间和状态到 `status/jobs.json`。
5. 提交后立即返回 jobid、资源、预计时长和下一次检查命令，不挂着 `sleep` 等待。用户回来要求继续时，在远端用 `squeue -u "${HPC_USER}"` 和 `sacct -u "${HPC_USER}" -X` 检查；先从站点配置设置变量。

### 阶段 2：失败诊断、自动纠错和重试

作业失败时先读实际含错误的 `rsl.error.*`，同时读 SLURM `.err/.log` 和 WPS 各阶段日志。按 `references/rsl-error-troubleshooting.md` 分 A/B/C 类：

- **A 参数级**：可自动修改并重新提交，例如 CFL、NaN/发散、层数不匹配、p_top、子域越界、输出参数、namelist 语法、资源数量、轻微时间窗错位。
- **B 资源/环境级**：先自动排查和解决；缺时次可补下载，磁盘只清 checkpoint 和旧日志，模块清单按源文件核对，排队/被 kill 最多重排一次，仍失败就停并报告。
- **C 科学设计级**：绝不自动改，必须问用户，例如物理方案、区域/嵌套根本设计、ERA5/GFS/FNL 驱动切换、影响跨实验可比性的改动。

每次重试写入案例目录 `retry_log.md`：现象、证据、分类、假说、改动、理由、预期效果、jobid。同一类错误最多 3 次，每次必须验证新假说；达到上限就给诊断报告并停下。

### 阶段 3：超算端提取

在配置的超算 Python 环境中运行 `scripts/extract_wrf.py`（四个子命令）或案例专用提取脚本，仅导出轻量结果：

- `plane`：平面场降采样 → npz（指定 `--var`/`--level`/`--time`，`--with-wind` 带风场，
  `--lat/--lon/--radius` 可裁子区域）；
- `series`：点/区域平均时间序列 → csv；
- `profile`：过指定点的垂直剖面 → npz（只支持三维变量）；
- `track`：台风中心逐时次路径 → csv（可选，仅台风个例用）。

不要默认提取台风路径，也不要默认做实况或模型对比；只有用户明确要求才增加对比。

### 阶段 4：回传

用 `scp` 将 CSV/NPZ/小型 NC 和图片回本地案例目录，保留远端文件清单和校验信息。严禁传回 `wrfout` 原文件。

### 阶段 5：本地绘图

使用 `scripts/wxplot.py` 公共规范和 `references/plot-conventions.md`。所有绘图函数接收 `language="en"`（默认）和 `style="draft"`（默认）：

- `draft`：150 dpi PNG；
- `presentation`：200 dpi PNG；
- `publication`：300 dpi PNG + PDF，可选单栏/双栏。

常用图型按数据选择：SLP+10 m 风、500 hPa 位势高度+风、850 hPa 风+涡度、降水、时间序列、垂直剖面、误差评分。台风 WRF/CMA/ERA5 路径图只作为可选示例。新图型必须扩展 `wxplot.py`，保持底图、配色、字体和落款一致。

## 资源路由

- 需求澄清和计划书：`references/requirement-intake.md`
- 昆山路径、模块、SLURM、WPS/real/WRF：`references/wrf-on-kunshan.md`
- rsl/SLURM/WPS 报错：`references/rsl-error-troubleshooting.md`
- `case.yaml` 字段和生成规则：`references/case-config-guide.md`
- 绘图语言、配色、规格、地图边界：`references/plot-conventions.md`
- **ERA5 输入陷阱（SST 0 K、Vtable、变量清单、land-sea mask）：`references/era5-input-pitfalls.md`**
- 配置校验：`scripts/validate_case.py`
- wrfout 轻量提取：`scripts/extract_wrf.py`（子命令 `plane` / `series` / `profile` / `track`）
- 本地公共绘图模块：`scripts/wxplot.py`
- 绘图模板（照抄改参数即可）：`scripts/example_plane_field.py`、`scripts/example_track_map.py`
- 行为评测集：仓库根 `evals/`，用真实场景检验 skill 是否可靠而非只验证“能跑”

## 环境注意

- 本地绘图依赖见 `requirements-local.txt`；远端依赖范围见 `requirements-hpc.txt`，需核对站点 Python/NumPy/编译器兼容性，不修改共享环境。
- 本地绘图需 matplotlib ≥3.9 与 cartopy；`wxplot.china_map` 固定使用 Natural Earth
  `10m` 分辨率。**不要改回 cartopy 默认的 110m** —— 多数机器只缓存了 10m，
  用 110m 会触发联网下载，离线环境直接失败。首次在新机器跑前，先确认
  `~/.local/share/cartopy/shapefiles/natural_earth/physical/` 下有 `ne_10m_land.shp` 等。
- 国界/省界矢量放用户配置的 `gis_root`（如 `/path/to/gis_data`），
  需要 `ne_10m_admin0/` 与 `ne_10m_admin1/` 两个子目录。
  ⚠️ 两个目录的判定字段**不同**：`admin_0_boundary_lines_land` 只有
  `ADM0_LEFT`/`ADM0_RIGHT`（没有 `ADM0_NAME`），`admin_1_states_provinces_lines`
  才有 `ADM0_NAME`。`wxplot.china_map` 已按文件分别配置；换用其他来源矢量时
  必须先核对字段名，否则会被静默跳过。
- `china_map` 默认 `strict=True`：给了 `gis_root` 却一条边界都没画出来会直接抛错。
  仅在离线演示等场景才显式设 `strict=False`。

## 交付检查

结束前确认：用户确认过计划书；远端 jobid 和状态已记录；成功产出 `wrfout`；提取文件可读；本地图片打开且无空白/乱码/重叠；图片注明变量、单位、资料来源、模式版本、起报时间；说明哪些结果是模拟、哪些是实况/再分析；没有泄露密钥；没有修改用户指定的只读参考资料。

**科学量核验（跑完不报错 ≠ 结果正确）**：网格 ≤ 15 km 的沿海个例，检查海岸线附近 2 m 气温最小值是否出现接近 −273 °C 的值；国界绘制条数大于 0；提取的诊断量单位与量级合理（如 500 hPa 位势高度约 5000–5900 gpm）。
