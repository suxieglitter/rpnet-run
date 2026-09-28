# 离线迁移与部署指南

在一台不通外网的 Linux 服务器上部署 rpnet-run 的完整流程。
每一步都在全新的 WSL2 Ubuntu + Miniconda 环境上从头复刻验证过，
验证数字见文末，逐项对上即部署成功。

## 一、准备：在有网的机器上制作离线包

```sh
# 1. 拿到本仓库和上游资源
git clone https://github.com/suxieglitter/rpnet-run.git
git clone https://github.com/jongwon-han/RPNet.git upstream

# 2. 组装迁移目录
mkdir -p rpnet-migrate/model rpnet-migrate/wheels rpnet-migrate/docs
cp -r rpnet-run rpnet-migrate/rpnet-run
cp upstream/model/RPNet_v1.h5 rpnet-migrate/model/
cp -r upstream/example rpnet-migrate/example
cp rpnet-run/docs/*.pdf rpnet-migrate/docs/
cp <本文件> rpnet-migrate/MIGRATE.md

# 3. 下载全部依赖的 wheel（约 1.2 GB，须用 Python 3.9 的 pip，
#    保证平台标签与目标机一致：Linux x86_64 + Python 3.9）
conda create -n builder python=3.9 -y
conda activate builder
pip download -d rpnet-migrate/wheels rpnet==0.1.0 skhash==1.1.5

# 4. 打包传走
tar -czf rpnet-migrate.tar.gz rpnet-migrate
scp rpnet-migrate.tar.gz user@目标机:~/
```

## 二、部署：在目标机上安装

目标机要求：Linux x86_64、已装 Miniconda/Anaconda。
（Apple Silicon 无 TensorFlow 2.7 原生 wheel，不支持；Intel Mac 未验证。）

```sh
tar -xzf rpnet-migrate.tar.gz
cd rpnet-migrate

conda create -n rpnet python=3.9 -y
conda activate rpnet

# 一条命令离线装齐（rpnet-run、SKHASH 及全部依赖）
pip install --no-index --find-links wheels --no-build-isolation ./rpnet-run

# 自检
rpnet-run --version
python -c "import rpnet, SKHASH; print('import OK')"
```

`--no-build-isolation` 是因为 keras-self-attention 只有源码包，
离线时 pip 不能联网搭构建环境，改用 conda 自带的 setuptools。

若目标机其实能访问 PyPI，可跳过 wheels，直接
`pip install rpnet skhash` 再 `pip install ./rpnet-run`。

## 三、验证（必做，5 分钟）

工具的路径守卫不接受含 `..` 的路径，先设解压位置变量：

```sh
export MIG=/解压位置/rpnet-migrate
# 解压在用户主目录内时无需下一行；否则指明允许目录
# export RPNET_RUN_ALLOWED_ROOT="$MIG"

cd "$MIG/example"
rpnet-run \
  --waveform-dir waveform \
  --catalog Kumamoto_catalog.csv \
  --phase Kumamoto_phase.csv \
  --stations hinet_station.csv \
  --model "$MIG/model/RPNet_v1.h5" \
  --vmodel "$MIG/example/vz.iasp91" \
  --add-sta \
  --out output_verify

SKHASH output_verify/hash2/control_file.txt
```

期望结果（实测值）：

- `100 rows -> pol_result.csv`，其中 2--3 条判不确定属正常随机涨落；
- 59 个台站名超过 4 字符自动改名（`sta_map.csv`）；
- `output_verify/hash2/OUT/out.csv` 两个事件：
  - `D20160420001172  265.4 / 41.4 / -88.2  quality A`
  - `D20160415000600  22.7 / 73.0 / -179.2  quality A`

两个机制解逐位对上即部署成功。对不上先查
`pip list | grep tensorflow`（应为 2.7.0）。

## 四、日常使用

见 `docs/rpnetrun_manual_v1.pdf`（操作手册：四个输入文件的格式、
参数说明、排错表）。示例数据来自上游 RPNet 仓库，其中 example2
（Buan，三分量）体积较大，未随默认迁移包走，需要时自行加入。

## 常见问题

| 现象 | 处理 |
|---|---|
| path is outside the allowed root | 设 `RPNET_RUN_ALLOWED_ROOT` 指向数据根目录 |
| path must not contain '..' | 所有参数写绝对路径（用 `$MIG` 变量写法） |
| output dir exists | 换新目录名或加 `--overwrite` |
| 想 1 度网格 | 需另编译 SKHASH Fortran 例程并扩 ncoor，见 docs 部署教程 |
