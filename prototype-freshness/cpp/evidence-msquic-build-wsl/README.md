# MsQuic v2.6.1：当前 WSL 的隔离构建证据

本轮只确认 Ubuntu WSL 能编译 MsQuic、构建其私有 QuicTLS，并从 C++20 链接公开 API。未执行 link smoke 的 main，没有启动 QUIC 连接、复制、交易或性能测试；不能据此声称 Windows 原生支持或生产容量。

| 可用产物 | 路径 |
|---|---|
| 头文件目录 | `/mnt/d/dev/Tyche-freshness-prototype/prototype-freshness/cpp/.quic-deps/msquic-v2.6.1/src/inc` |
| 动态库 | `/home/alan/.cache/tyche-prototypes/quic-20260919/msquic-release/bin/Release/libmsquic.so.2.6.1` |
| 库链接名 | 同目录 `libmsquic.so.2`、`libmsquic.so` |
| 仅编译链接的 ELF | `/home/alan/.cache/tyche-prototypes/quic-20260919/msquic-release/msquic_link_smoke` |

动态库 SHA256：`10d88b8fcdc411952430525bdc08885ca3b09899e371f2924f7c6c41bc516b7a`。
`msquic.h` SHA256：`3ebde22085df627140fd6208c638a9a3cd7dd3da9bd270f64f022b1c46b1bc4f`。

`ldd` 和 `readelf -d` 显示库的唯一 NEEDED 项为 `libc.so.6`，无系统 `libssl/libcrypto` 动态依赖。SONAME 为 `libmsquic.so.2`；公开动态符号为 `MsQuicOpenVersion` 和 `MsQuicClose`。C++20 smoke 使用 `-Wall -Wextra -Wpedantic -Werror` 和 `-isystem` 引入官方头文件，成功链接；其 API 调用没有运行。

## 精确来源及配置

来源为 [Microsoft 官方 MsQuic 仓库](https://github.com/microsoft/msquic/tree/v2.6.1)，tag `v2.6.1` 固定到 `a01333cf7c2659cce0ff03ef3f21e1ff15bb5b83`。仅初始化其必需的 [QuicTLS 子模块](https://github.com/quictls/openssl/tree/ff36838bb69801cad56823159a036977bcbe5c75)，父仓 gitlink 为 `ff36838bb69801cad56823159a036977bcbe5c75`，版本文件标为 `3.1.7+quic`。两仓均只浅取一个提交；googletest、CLOG、另一个 OpenSSL 和 XDP 子模块未下载。未修改上游源码，工作树核验保持干净。

构建机为 Ubuntu WSL，Linux `6.18.33.2-microsoft-standard-WSL2`、x86_64，GCC/G++ 13.3.0、CMake 3.28.3、Ninja 1.11.1、GNU make 4.3、Perl 5.38.2。CMake 没找到可选 libnuma，仍成功完成此配置，未安装任何系统包。

明确配置：

```text
CMAKE_BUILD_TYPE=Release
CMAKE_EXPORT_COMPILE_COMMANDS=ON
QUIC_TLS_LIB=quictls
QUIC_USE_SYSTEM_LIBCRYPTO=OFF
QUIC_USE_EXTERNAL_OPENSSL=OFF
QUIC_ENABLE_LOGGING=OFF
QUIC_BUILD_TEST=OFF
QUIC_BUILD_TOOLS=OFF
QUIC_BUILD_PERF=OFF
QUIC_BUILD_SHARED=ON
QUIC_LINUX_IOURING_ENABLED=OFF
```

该 tag 没有单独的 artifacts 开关；只选择 `msquic` 库目标，不构建额外测试/工具/性能程序。QuicTLS 使用上游给定的 `no-shared no-tests` 等选项，其 `make install_dev` 前缀完全位于上述原型缓存的 `_deps/opensslquic-build/quictls`。日志中的 `--openssldir=/usr/lib/ssl` 是上游配置/信任位置默认值，不是此次私有库安装前缀；没有运行系统安装、sudo、包管理器或官方 prepare 脚本。

依赖源码在 D 盘 `.quic-deps/`，局部 `.gitignore` 防止把下载的依赖加入原型提交。ext4 构建缓存是本原型专用；完成后源码约 156 MiB，缓存约 53 MiB。开始前 Windows C 盘可用约 25.25 GiB；不把 guest ext4 的虚拟最大容量当作主机剩余空间。

## 可重复的本机步骤

从 Linux 的 `prototype-freshness/cpp` 目录运行；脚本固定上述来源与本机隔离路径，拒绝覆盖已有源码/配置：

```sh
python3 msquic_dependency_build.py fetch
python3 msquic_dependency_build.py fetch-tls
python3 msquic_dependency_build.py inspect
python3 msquic_dependency_build.py configure
python3 msquic_dependency_build.py build
python3 msquic_dependency_build.py link
python3 msquic_dependency_build.py archive
```

`build` 限制 Ninja 并行度为 4；QuicTLS 上游用 ProcessorCount/nproc 生成 make 并行参数，故仅在构建子进程设置 `OMP_NUM_THREADS=4` 并核对生成的 `make install_dev -j4`。脚本先单独构建 `OpenSSL_Target`，再构建 MsQuic，避免新构建时两层工作叠加。每约 5 秒观察构建目录占用，超过 4 GiB 或 C 盘可用低于 8 GiB 时停止该脚本自己的构建进程组；这是观察后停止的保护，不是文件系统配额。没有改变 WSL 配额、系统时钟或 CPU 电源设置。

首次实际构建为组合 `msquic --parallel 4`，其内部 make 已为 `-j4`；命令和原始日志完整保留。之后收紧为分阶段入口，并核验两个目标均已完成，无重新编译。脚本不自动删除、重置或重下已有依赖。

## 证据索引

- `commands.json`：实际命令、工作目录、子进程环境覆盖、起止 UTC、退出码及 stdout/stderr 哈希；每条原始输出单独保存。
- `build-inputs/`：上游 CMake、gitmodules、版本及许可证，实际 CMakeCache、Ninja/compile_commands、QuicTLS Makefile、最终隔离脚本和 link smoke 源码。
- `dependency.json`：准确 include/library 路径、提交、`src/inc` 下 `.h` 文件的哈希、动态库/静态 TLS 库/未运行 smoke 的 SHA256。
- `audit.json`：证据文件的完整字节哈希。目录属性为 `* -text -whitespace`，防止 Windows Git 改写字节。

初次手写 PowerShell→WSL 探查中的 Perl 内联字符串及未引用的 tag 花括号被 shell 解析拒绝；改用结构化 subprocess 参数和 `perl -v` 后确认工具正常。这些是探查命令的引用问题，不是缺少依赖或构建失败。隔离脚本记录的获取、配置、编译和链接步骤均成功。
