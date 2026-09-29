# rpnet-run

RPNet（P 波初动极性判定，Han et al., 2025, SRL）的命令行封装。
一条命令完成：读表 → TauP 到时 → 切窗 → 极性预测 → 阈值筛选 → 生成 SKHASH 输入文件，
不再需要复制 example 目录、改 `hyperparams.py` 和 `control_file0.txt`。

底层逐行沿用上游 `example/run_RPNet.py`（v0.1.0）的流程；`mean_threshold` 一处
笔误按 example2 的正确写法实现。

## 安装

Python 必须是 3.9：上游 rpnet 依赖的是 2021 年的版本组合（TensorFlow 2.7、
numpy 1.19.5 等），官方只为 Python 3.9 发布过现成安装包；实测 3.10 及以上
（含 3.14）pip 会转源码编译并直接失败。

务必先建独立环境装好 rpnet，再做其他操作：rpnet 锁定 TensorFlow 2.7、
numpy 1.19.5 等 2021 年版本，混装进已有环境会把原有包整体降级。

```sh
conda create -n rpnet python=3.9 -y     # 注意显式写 python=3.9
conda activate rpnet
python --version                        # 必须显示 3.9.x，否则后面全报错

# 第一步：上游包（TensorFlow 2.7 等依赖一并安装，约 0.5 GB）
pip install rpnet
python -c "import rpnet; print('rpnet OK')"    # 装好先自检

# 第二步：其余两个包
pip install skhash             # SKHASH 1.1.5，与上同环境
pip install git+https://github.com/suxieglitter/rpnet-run.git
rpnet-run --version
```

离线服务器部署见 [MIGRATE.md](MIGRATE.md)（自制离线包 + 全流程验证数字）；
现成的离线迁移包（1.2 GB，含全部 wheel 与模型权重）在
[Releases](https://github.com/suxieglitter/rpnet-run/releases/tag/v0.1.0) 下载，
内网或镜像不全的机器用它，一条命令离线装齐。
模型权重 `RPNet_v1.h5` 从[上游仓库](https://github.com/jongwon-han/RPNet)的
`model/` 目录获取（约 62 MB）。

## 文档

- [docs/rpnetrun_manual_v1.pdf](docs/rpnetrun_manual_v1.pdf) — 操作手册：
  面向已有 P 震相的台网用户，四个输入文件的格式逐页写清
- [docs/rpnet_workflow_v1.pdf](docs/rpnet_workflow_v1.pdf) — 部署教程：
  上游脚本路线、1 度网格 Fortran 编译、常见坑

## 60 秒上手（以仓库自带 example 为例）

```sh
cd RPNet/example

rpnet-run \
  --waveform-dir waveform \
  --catalog Kumamoto_catalog.csv \
  --phase Kumamoto_phase.csv \
  --stations hinet_station.csv \
  --model /abs/path/to/RPNet/model/RPNet_v1.h5 \
  --vmodel /abs/path/to/RPNet/example/vz.iasp91 \
  --add-sta \
  --out output01

SKHASH output01/hash2/control_file.txt    # 震源机制，结果在 output01/hash2/OUT/
```

不想跑 SKHASH 就省略 `--vmodel`，只出 `output01/pol_result.csv`。

已验证（WSL2、CPU、5 度网格）：上例 0.3 分钟出 100 条极性（97 条 U/D），
SKHASH 2.5 秒出两个机制解 265.4/41.4/-88.2、22.7/73.0/-179.2，
与上游脚本的逐台极性 100% 一致。

## 输入：四个文件

| 参数 | 内容 | 必需列 |
|---|---|---|
| `--waveform-dir` | 波形目录，布局 `<事件id>/<台站>.*`，垂直通道 `*Z` 优先、`*U` 兜底，非 100 Hz 自动插值 | — |
| `--catalog` | 事件目录 CSV | 发震时刻、事件 id、lat、lon、dep（mag 可选，缺省补 0） |
| `--phase` | 震相 CSV | 事件 id、sta、P 到时、S 到时 |
| `--stations` | 台站 CSV | sta、lat、lon、elv（net、chan 可选） |

列名不同时用 `--time-col / --id-col / --ptime-col / --stime-col` 指定。
事件目录与震相的时间要同一时间标准（UTC 最省事）。

## 常用参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--add-sta` | 关 | 补上「有波形、无拾取」的台站（自动用 TauP 理论到时） |
| `--no-taup` | 开(TauP) | 关闭后沿用目录里的原始到时 |
| `--keep-initial-phase` | 关 | 已有拾取保留原值，只补缺的 |
| `--taup-model` | iasp91 | 可填 ak135 或自定 npz 绝对路径 |
| `--iteration` | 100 | 蒙特卡洛迭代次数；prob 取均值、std 取标准差；0 为单次 |
| `--std-threshold` | 0.2 | std 超过该值判为不确定（K） |
| `--mean-threshold` | 0（关） | prob 低于该值判为 K；example2 用 0.95 |
| `--keep-unknown` | 关 | K 也写进 SKHASH 输入（默认剔除） |
| `--cores` | 5 | 预处理并行数 |
| `--gpu` | 空(CPU) | 例如 `0` 用第一块 GPU |
| `--dang` | 5 | SKHASH 网格角步长（度）。1 度需另编译 Fortran 例程并扩 ncoor，见教程 |
| `--loc-uncert` | 0（关） | 震源位置不确定度（km，统一一个数）。写入 phase.txt 头行并打开震中扰动，SKHASH 蒙特卡洛试验才真正扰动位置，fault_plane_uncertainty 才含定位误差贡献；不加则维持上游写死的 0 km（各次试验几何全同） |
| `--overwrite` | 关 | 输出目录已存在时允许清空重建（默认报错保护） |

## 输出

```
<out>/pol_result.csv     全部预测：predict(U/D/K)、prob、std、TauP 前后到时
<out>/MSEED/<id>/<sta>.mseed   切窗存档（P±2.5 s、高通 1 Hz、100 Hz）
<out>/sta_map.csv        台站改名对照（仅当台站名超过 4 字符时生成）
<out>/hash2/IN/          HASH 格式 station.txt / phase.txt
<out>/hash2/control_file.txt   直接交给 SKHASH：SKHASH <out>/hash2/control_file.txt
<out>/hash2/OUT/         SKHASH 结果（out.csv：strike、dip、rake、quality）
```

台站名超过 4 个字符会自动改名 S001…（HASH 震相文件台站列只有 4 字符宽），
对照表在 `sta_map.csv`；短名台网不受影响。

## 安全限制

- 传入路径不得包含 `..`；请用绝对路径或普通相对路径。
- 所有输入和输出必须位于允许目录树内，默认用户主目录；
  数据在别处时设 `RPNET_RUN_ALLOWED_ROOT=/数据根目录` 放开。

## 未封装的部分

- S/P 振幅比（上游 example2 的 hash3 路线）不在本封装内，需要时直接用上游脚本。
- 训练/微调：上游 v0.1.0 未提供。
