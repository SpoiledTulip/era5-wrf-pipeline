# 昆山曙光 WRF 运行约定

## 私有站点配置

使用前从用户的私有配置获取以下字段；缺项先确认，禁止照抄占位符提交。环境变量不会由本 skill 自动加载，执行命令前须显式设置；YAML 也不会自动展开环境变量。

- `HPC_SSH_ALIAS`：SSH 配置中的别名
- `HPC_USER`：超算账号
- `HPC_WORK_ROOT`：远端工作根目录
- `WRF_ROOT`、`WPS_ROOT`：站点软件安装目录
- `HPC_PYTHON`：远端 Python 解释器绝对路径
- `SLURM_PARTITION`：可用分区；调度为 SLURM
- `WPS_GEOG_ROOT`：共享静态地理数据目录
- `LOCAL_CASE_ROOT`、`GIS_ROOT`：本地案例及地图数据目录

私有配置仅在本机保留，不提交到 GitHub。下列命令中的变量应在远端环境设置。

## 编译环境

以用户提供的站点运行方案为准。下面是模块配置示例，不保证当前站点可用；提交前检查目标 WRF/WPS 二进制所需环境，不凭印象切换版本。

```bash
module purge
module load compiler/intel/2017.5.239
module load mpi/intelmpi/2017.4.239
module load mathlib/zlib/1.2.8/intel
module load mathlib/hdf5/1.8.12/intel
module load mathlib/netcdf/4.6.2/intel
module load mathlib/pnetcdf/1.12.1/intel
module load mathlib/libpng/1.2.50/intel
module load mathlib/jasper/1.900.1/intel
```

## 目录

```text
case/
├── case.yaml plan.md retry_log.md
├── data/           ERA5 与下载日志
├── wps/            namelist、geo/met、ungrib 子目录
├── wrf/            namelist、real/wrf、wrfout、rsl
├── extract/        CSV/NPZ/小型 NC
├── plots/          图片
├── logs/
└── status/jobs.json
```

## WPS 顺序

1. `geogrid.exe` 生成 `geo_em.d0*.nc`。
2. PLEV 独立目录：链接 `Vtable.ERA-interim.pl` 和 PLEV GRIB，运行 `ungrib.exe`，前缀 `PLEV`。
3. SFC 独立目录：同样运行，前缀 `SFC`。
4. 把 `PLEV:*`、`SFC:*` 链回 WPS 根目录，`metgrid fg_name='PLEV','SFC'`。

## SLURM

```bash
sbatch wps.sbatch
sbatch --dependency=afterok:<wps_jobid> real.sbatch
sbatch --dependency=afterok:<real_jobid> wrf.sbatch
squeue -u "${HPC_USER}"
sacct -u "${HPC_USER}" -X
```

WRF 运行脚本使用 `mpirun -np $SLURM_NTASKS ./wrf.exe` 或经验证的 `srun --mpi=pmi2`，不要在登录节点前台跑。保留 `.out/.err`、`rsl.out.*`、`rsl.error.*`。

## 数据与安全

ERA5 用 `cdsapi` + `~/.cdsapirc`，只写“已配置”不写 key。脚本要幂等：目标文件存在且大小合理就跳过；下载失败带递增重试。只回传提取结果和图。
