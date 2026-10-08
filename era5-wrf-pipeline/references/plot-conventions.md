# 绘图规范

## 语言与规格

所有标题、轴名、图例、色标、地名和落款由 `language` 控制，默认 `en`；变量名和单位保持国际符号：`SLP (hPa)`、`wind speed (m/s)`、`geopotential height (gpm)`、`500 hPa`、`accumulated rainfall (mm)`。

- `draft`：150 dpi PNG，诊断；
- `presentation`：200 dpi PNG，组会投影；
- `publication`：300 dpi PNG + PDF，投稿；支持单栏/双栏。

## 版式

- 海洋 `#d6e8f0`，陆地 `#f5f0e6`，湖泊 `#cfe3ec`；
- 国界、台湾、南海诸岛必须遵守国家标准。Natural Earth 只作区域示意，图注说明边界性质；
- 国界/省界/海岸线统一使用 **10m** 矢量（与省界同级；cartopy 默认的 110m 多数机器未缓存，
  会触发联网下载导致离线失败）。省名用 `path_effects.withStroke` 白描边；
- 经纬网显示经纬标签，关闭 top/right；
- 标题简洁，图注落款写数据来源、WRF 版本、起报时间、区域和语言；
- 不默认叠加观测、ERA5 或其他模型；只有用户明确要求对比才叠加。

## 省名标注

`wxplot.PROVINCE_LABELS`（en/zh）与 `wxplot.PROVINCE_XY`（锚点坐标）覆盖 34 个省级行政区，
按 `extent` 自动筛选落在范围内的省并剔除贴边者。台湾、香港、澳门按省级行政区统一标注，
不特殊处理。要新增或微调可在调用时传 `label_provinces=[...]`。

## 常用图型

`wxplot.py` 提供原语：`plane`（等值填色）、`contour`（等值线+数值）、`wind_barbs`（风羽）、
`quiver`(箭头)、`track`（路径）、`add_colorbar`、`footnote`、`save`。
可组合出 SLP+10m 风、500 hPa 高度+风、850 hPa 风+涡度、降水、时间序列、剖面和误差评分。
新图型沿用同一底图、字体、配色、落款与 `language/style` 参数。

现成模板：`scripts/example_plane_field.py`（读 `plane` 导出的 npz）、
`scripts/example_track_map.py`（读 `track` 导出的 csv，可叠实况对比）。
