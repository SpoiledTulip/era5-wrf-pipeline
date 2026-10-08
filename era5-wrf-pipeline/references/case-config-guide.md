# 案例配置字段

建议用 YAML；生成器可用 PyYAML，若环境没有则先安装到案例私有环境，不修改共享 Python 环境。示例路径必须替换为部署配置的真实路径。

```yaml
name: example_case
start_utc: "2026-08-05_00:00:00"
duration_hours: 72
output_interval_minutes: 180
domain:
  projection: lambert
  ref_lat: 28.0
  ref_lon: 129.0
  truelat1: 30.0
  truelat2: 60.0
  stand_lon: 129.0
  geog_data_res: default
  geog_data_path: /path/to/WPS_GEOG
  domains:
    - dx: 15000
      dy: 15000
      e_we: 170
      e_sn: 108
      parent_id: 1
      parent_grid_ratio: 1
      i_parent_start: 1
      j_parent_start: 1
    - dx: 5000
      dy: 5000
      e_we: 136
      e_sn: 148
      parent_id: 1
      parent_grid_ratio: 3
      i_parent_start: 10
      j_parent_start: 37
vertical:
  e_vert: 37
  p_top_requested: 5000
  num_metgrid_levels: 38
physics:
  mp_physics: 6
  cu_physics: 1
  bl_pbl_physics: 1
  sf_sfclay_physics: 1
  sf_surface_physics: 2
  ra_lw_physics: 4
  ra_sw_physics: 4
driver:
  source: ERA5
  interval_seconds: 21600
  area: [39, 104, 17, 141]
  pressure_levels: [1000, 925, 850, 700, 500, 300, 200, 100, 50]
```

## 自检规则

- 对每个子域，`(e_we-1)` 和 `(e_sn-1)` 应满足父子网格关系；子域在父域内且四周至少留 5 个父格点。
- `num_metgrid_levels` 等于实际 `met_em` 垂直层数；`e_vert` 通常比它少 1，但以 real.exe 和实际资料为准。
- `p_top_requested` 不得高于 ERA5 请求的最高资料层。
- `end_utc = start_utc + duration_hours`；ERA5 请求必须覆盖完整窗口，并留必要 spin-up。
- `interval_seconds` 等于输入驱动时次间隔；WRF history 输出频率另行设置。
- 不要自动改变物理方案。配置无效时先报告属于 C 类科学设计还是 A 类机械错误。
