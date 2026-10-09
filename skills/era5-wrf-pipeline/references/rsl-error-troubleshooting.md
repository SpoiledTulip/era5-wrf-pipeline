# WRF/WPS 失败诊断表

先读真正包含错误的 `rsl.error.*`，再读作业 `.err/.log`、WPS `geogrid/ungrib/metgrid` 日志。不要看到一个关键词就盲改。

| 关键词/现象 | 分类 | 判定与处理 |
|---|---|---|
| `CFL`, `time step too large`, `W DAMPING` | A | 将 `time_step` 按约 90→72→54 s 降低；每次新假说、重提作业。 |
| `NaN`, `floating point`, `FPE`, `blow-up` | A | 先减 `time_step`；仍有证据时降低 `diff_opt`，记录科学影响。 |
| `num_metgrid_levels`、`metgrid level` 不一致 | A | 统计 `met_em` 的实际层数，改 `num_metgrid_levels`；核对 `e_vert`。 |
| `p_top_requested` 高于资料顶层 | A | 调到 ERA5 可支持的顶层；不得凭空增加资料层。 |
| `domain not inside`, `nest`, `i_parent_start`、`e_we` | A | 用配置校验重新算子域边界、整除和 5 格边界，修位置/格点数。 |
| `namelist parsing`, `invalid namelist`, `Fortran` 语法 | A | 修逗号、类型、字段名和多域数组长度；重新生成而非手改副本。 |
| `No such file`, 缺 `met_em`/`wrfinput` | A/B | 先查路径、软链和上游 job 状态；上游失败不得直接重提 WRF。 |
| 缺某个 ERA5 时次 | B | 比对 start/end/interval；必要时用 cdsapi 补下载并保持同一 Vtable/前缀。 |
| `geog_data_res`、缺地理数据 | B | 先问用户是否允许降级分辨率；禁止静默改变地理数据科学设置。 |
| `No space left`, quota | B | 只清旧日志和 `wrfrst` checkpoint；绝不删除 wrfout 或原始 ERA5。 |
| module/MPI/NetCDF 动态库错误 | B | 按 `wrf-on-kunshan.md` 和源文档核对模块；一致仍失败就停并报告。 |
| `TIMEOUT`, `CANCELLED`, `OUT_OF_MEMORY`, 排队超时 | B | 检查资源和队列，最多调整资源重排一次；仍失败停下。 |
| 需要换微物理/积云/PBL | C | 必须问用户，不能自动改。 |
| 要换区域、嵌套根本设计、驱动源 | C | 必须问用户。 |
| 结果需与旧实验可比但参数要变 | C | 必须问用户并说明不可比风险。 |

## 重试日志模板

```text
### Retry <n> / <timestamp>
- jobid:
- stage:
- symptom:
- evidence:
- class: A / B / C
- hypothesis:
- change:
- reason:
- expected effect:
- result:
```

同一类错误最多 3 次，且每次必须验证新的明确假说。C 类立即停；B 类解决不了立即停。
