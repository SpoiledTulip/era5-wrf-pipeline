# ERA5 驱动 WRF 的已知陷阱

本文件记录用 ERA5 驱动 WRF 时**跑得通但结果错**的坑。
这类问题不报错、日志干净、图也出得来，只能靠事先知道才避得开。

---

## 1. SST 在陆地上是 0 K（高分辨率网格必踩）

### 现象

在 15 km 及更细的网格上，**海岸线附近的 2 m 气温接近绝对零度（约 −273 °C）**。
内陆和远海都正常，只有海岸带一圈数值崩掉。

### 原因

ERA5 的海表温度 `SST` 在陆地点上以 **0 K** 作为填充值，不是 NaN，也不是合理替代值。
粗网格上这种异常点被平滑掉、不易察觉；网格越细，落在陆地上的 SST 格点越多，
插值后就会把 0 K 直接带进模式。

### 证据

NCAR 支持论坛与 WRF 官方仓库均确认此为已知问题：

- `wrf-model/WRF` issue #1637，NCAR 的 weiwangncar 确认：
  「ERA5 的 SST 在陆地上被掩膜为填充值，15 km 与 3 km 网格上会出现海岸线附近
  2 m 温度接近绝对零度」。
- 同一讨论指出，ERA5 的 `SKINTEMP` 与水上 `SST` 基本一致，
  因此移除 SST 改用 SKINTEMP 是可行的。

### 影响面

- **任何**沿海或含海陆交界的区域模拟，只要分辨率到 15 km 量级就可能中招。
- 对沿海降水、海雾、台风登陆、海陆风研究是**致命错误**——
  这些正是最依赖海岸带热力场的题目。
- 本 skill 的示例配置 `d01 = 15 km / d02 = 5 km` 正落在此范围内。

### 三种解法（任选其一，但必须选）

| 方案 | 做法 | 适用 |
|------|------|------|
| A. 移除 SST | 在 Vtable 中删掉 `SST` 条目，仅保留 `SKINTEMP` | 最简单，推荐默认 |
| B. 设填充值 | 在 `METGRID.TBL` 中把 SST 的 `fill_missing` 设为合理值（如 285.） | 想保留 SST 字段时 |
| C. 陆海掩膜插值 | 对 SST 增加 `interp_land_mask = LANDSEA(1)` | 最规范，需改 METGRID.TBL |

方案 C 的参考写法（`METGRID.TBL`）：

```
name=SST
        interp_option=sixteen_pt+four_pt+wt_average_4pt+wt_average_16pt+search
        fill_missing=0.
        missing_value=-1.E30
        flag_in_output=FLAG_SST
        interp_land_mask = LANDSEA(1)
        masked=land
```

### 交付前必须做

在图上检查**海岸线附近的 2 m 气温最小值**。若出现接近 −273 °C 的值，
说明 SST 陷阱没有处理。建议在 `case.yaml` 增加显式字段：

```yaml
driver:
  source: ERA5
  sst_handling: vtable-remove    # vtable-remove | fill-missing | land-mask
```

未声明该字段却使用了 ≤ 15 km 网格时，应在阶段 0 告警，不得静默放过。

---

## 2. Vtable 的选择

处理 ERA5 时，社区实践有两种：

- `Vtable.ERA-interim.pl`：本 skill 默认使用。多数情况下可用。
- `Vtable.ECMWF`：NCAR 论坛（Ming Chen）对 ERA5 的建议。
  有用户反馈仅用 `.pl` 会得到错误的 2D 变量（如 `TT` 变成二维），
  换 `Vtable.ECMWF` 后正常；也有用户表示 `.pl` 一直可用。

**建议**：先按 `.pl` 跑，但在 metgrid 完成后核对 `met_em` 里的三维变量
（如 `TT`、`UU`、`VV`）确实是三维。若不是，换 `Vtable.ECMWF` 重跑 ungrib。

注意：无论用哪个 Vtable，**陷阱 1 都需要单独处理**——它与 Vtable 选择无关，
因为问题出在 SST 这个字段本身。

---

## 3. 气压层与单层必须分别下载、分别 ungrib

ERA5 的 3D（气压层）与 2D（单层）在不同数据集，需两次请求、两个 ungrib 目录、
两个前缀，最后把中间文件链回根目录做 metgrid：

```
WPS/ungrib_PLEV/  → 前缀 PLEV，用 Vtable.ERA-interim.pl，链接 3D GRIB
WPS/ungrib_SFC/   → 前缀 SFC，用同一 Vtable（含单层字段），链接 2D GRIB
WPS/              → 链回 PLEV:* 与 SFC:*，metgrid 用 fg_name='PLEV','SFC'
```

必须下载的 2D 变量至少包括：`surface_pressure`、`mean_sea_level_pressure`、
`10m_u/v_component_of_wind`、`2m_temperature`、`2m_dewpoint_temperature`、
`sea_surface_temperature`（若走方案 A 则不需要）、`skin_temperature`、
`soil_temperature_level_1..4`、`volumetric_soil_water_layer_1..4`、
`snow_depth`、`sea_ice_cover`、`land_sea_mask`。

---

## 4. land-sea mask 可能需单独取

`land_sea_mask` 不随时间变化，某些下载途径不会自动带出。
若 `met_em` 里缺少 `LANDSEA`，方案 C 无法使用，且部分物理过程会受影响。
下载后务必用 `ncdump -h` 确认 `LANDSEA` 存在。

---

## 5. 时次与 interval_seconds 必须对齐

ERA5 默认逐小时。若用 6 小时间隔驱动，
`interval_seconds = 21600` 且请求的时次必须覆盖完整积分窗口并留出 spin-up。
缺任一时次会在 real 或跑动中才暴露，前期不会报错。

统计请求到的时次数，与 `duration_hours / (interval_seconds / 3600) + 1` 比对。

---

## 6. num_metgrid_levels 必须从 met_em 实测

不能按下载的气压层数猜测。WPS 完成后：

```bash
ncdump -h met_em.d01.<日期>.nc | grep num_metgrid_levels
```

把实测值填入 `case.yaml`，再执行：

```bash
python scripts/validate_case.py case.yaml --metgrid-levels <实测值>
```

注意 `e_vert` 是模式自身垂直网格设置，与资料层数**不存在固定的差一层关系**。

---

## 一句话

以上各条都属于「跑完不报错、但结果是错的」这一类。
**报告与图正常不等于结果正确**；科学量的合理性必须单独核验。
