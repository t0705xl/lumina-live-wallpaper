# Lumina Live Wallpaper & Monet Desktop System
## 阶段交接报告与人物/任务现状 (Handover & Status Report)

- **生成时间**: 2026-11-11（2026-11-13 更新：自绘液态玻璃、独立扩展 UUID、概览缩放修复，见第二节第 5 条；2026-11-14 更新：屏幕尺寸播放副本、分屏暂停、概览卡片实时壁纸、真实桌面实测，见第二节第 6 条与第六节）
- **运行平台**: Microsoft Surface Pro 7+ (Fedora 44 / Linux 6.19 / GNOME 50 Wayland，2736×1824，缩放 200%)
- **代码仓库**: `~/my-video/lumina-live-wallpaper`（`glass-rework` 已于 2026-11-14 快进合并进 `main` 并推送到 GitHub）
- **系统核心服务**: `live-wallpaper.service` | `monet-panel.service`

---

## 一、 人物与角色分工现状 (Roles & Ownership)

| 角色 / 人物代号 | 负责阶段 | 核心权责与工作范畴 | 当前交付状态 |
| :--- | :--- | :--- | :--- |
| **Argon (架构与原型)** | 阶段一：奠基与架构建立 | 搭建 GStreamer 基础管线、设计 GJS 顶栏扩展原型、初步规划 Material You 取色原型与守护进程体系。 | 已完成初期架构设计，并平稳交接。 |
| **Antigravity (当前调优者)** | 阶段二：本土化痛点攻坚与视觉重构 | 针对 Surface Pro 7+ 与 GNOME 50 环境：<br>1. 硬件级 30fps 限帧与多媒体功耗大幅压降；<br>2. 莫奈色彩直方图聚类重构（根治红信件偏色）；<br>3. 规避 GNOME 设置面板 `NOFOLLOW_SYMLINKS` 缺陷（硬链接方案）；<br>4. 状态栏液态玻璃去雾、去发白内阴影，修复 `RENAMED` 样式热重载失效漏洞。 | 本阶段任务全部交付并完成本地 Git 归档，随时可由 Argon 或下一负责人接力。 |
| **Claude Code (2026-11-13 / 14)** | 阶段二续：玻璃重做、性能与稳固 | 自绘圆角背景模糊 `glass.js`（含自写缓存两遍高斯模糊）、OKLCH 取色与 WCAG 对比度求解、概览底层壁纸与卡片实时壁纸、扩展迁出借用的 UUID、屏幕尺寸 30 fps 播放副本、分屏暂停、安装脚本修复、无头预览工具 `dev/preview`。 | 已合并进 `main` 并推送；新代码已在本机生效（2026-11-14 开机后），等待用户验收。 |
| **Next Maintainer (接班维护者)** | 阶段三：长效演进（待办建议） | 多显示器环境适配、壁纸自动轮播策略、打包 RPM/Flatpak 发行版、在电池供电下实测功耗瓦数。 | 待启动 |

---

## 二、 核心技术攻坚成果与指标对比

### 1. 性能、功耗与能效优化
- **30fps 硬件帧率约束**：接入 GStreamer `videorate (drop-only=true, max-rate=30)`，彻底消除了 Surface Pro 7+ 移动核显多余的高刷负载。
  - **单核 CPU 占用**：由 **11.6%** 骤降并稳态锁定在 **4.5%**（降幅达 **61.2%**）。
  - **内存表现**：稳态内存驻留 ~540MB，且全程无内存泄漏。
- **动态平滑过渡**：两段视频壁纸切换时，引入 `opacity: 0.24` 微降过渡，彻底消除了壁纸切换时的黑场闪烁感。
- **窗口遮挡智能休眠**：扩展把主显示器上可见常规窗口的边框矩形裁到工作区内求并集，覆盖工作区 ≥ 92% 时暂停视频解码（单窗口最大化/全屏、Super+←/→ 左右分屏、几个窗口拼满都算）；窗口拖动或缩放结束时也会重新判断（2026-11-13 前只认单个最大化/全屏/≥94% 的窗口，分屏时视频照常解码）。休眠时自动挂起，唤醒时自动重载自愈。

### 2. 莫奈取色引擎重构 (Monet Engine)
- **痛点原因**：原算法仅统计 RGB 均值与简单极值，画面中哪怕只有一张小小的红色信件或噪点像素，都会导致整个桌面主题被错误染成高饱和刺眼大红。
- **解决方案**：重构为 **36-bin 圆形色相直方图（10°/桶） + 5-tap 循环高斯平滑 + 区域中心/顶栏空间加权 + 面积色度聚类**。
- **全系统色彩联动流向**：
  - **Libadwaita / GTK3**：自动映射主调为最协调的官方主题强调色（Accent Color）。
  - **Ptyxis 终端**：自动注入当前莫奈配色，并保持 0.94 磨砂微透明。
  - **GNOME Shell 顶栏**：实时计算背景主色调，驱动液态玻璃胶囊气泡的折射边框与投影。

### 3. 系统设置「外观」面板壁纸识别修复
- **痛点原因**：GNOME 42+ 的 `bg-recent-source.c` 强制使用 `G_FILE_QUERY_INFO_NOFOLLOW_SYMLINKS`，所有软链接均被识别为 `inode/symlink` 从而被系统设置过滤，用户无法在「系统设置 -> 外观」看到动态壁纸。
- **解决方案**：引入**硬链接（Hard Link）同步架构**。将壁纸封面图通过硬链接链接到 `~/.local/share/backgrounds/`，0 额外磁盘占用，且 `GFileInfo` 完美返回 `image/png`，在系统设置中完整保留「▶ LIVE」角标动态壁纸。

### 4. 顶栏液态玻璃视觉重构与热重载排障
- **雾蒙蒙灰带成因**：原气泡设置了垂直双色阶渐变（顶部白半透 + 底部深褐半透），在垂直方向线性插值时，中段文字区域混出色相抵消的灰浊色，肉眼呈现出肮脏白雾。
- **光学质感重塑**：
  - 气泡改为 `background-gradient-direction: none !important;`，使用统一纯净极薄微晶底色（Dark: `rgba(..., 0.12)`）。
  - 剔除发白内阴影（`box-shadow: inset`），改用纯外部景深阴影（`0 3px 12px rgba(0,0,0,0.22)`）与单层边缘晶体反光轮廓（`border: 1px solid rgba(255,255,255,0.24)`）。
  - 清除文字和图标的黑色暗影（`text-shadow: none`、`icon-shadow: none`），文字呈现纯白 `#FFFFFF`。
- **热重载失效修复**：
  - 发现底层写入使用了 `os.replace`（产生 `IN_MOVED_TO` / `Gio.FileMonitorEvent.RENAMED` 事件 8），原扩展监听白名单直接过滤了事件 8，导致 CSS 从未生效。
  - 修复了 `extension.js` 的过滤白名单，并改为直接覆盖写入，确保修改后毫秒级无缝防抖热重载。

### 5. 2026-11-13：自绘液态玻璃、独立 UUID、概览缩放
- **自绘背景模糊 `glass.js`**：顶栏胶囊、快捷设置、Dock 都用 BlitNode → BlurNode → 圆角遮罩/饱和度/折射着色器绘制；参数由 CSS 的 `-lumina-blur / -lumina-saturation / -lumina-brightness / -lumina-refraction / -lumina-max-luma / -lumina-min-luma` 控制，`-lumina-blur: 0` 即关闭。顶栏与 BoxPointer 必须 `OffscreenRedirect.NEVER` 才能采样背景。
- **莫奈取色改为 OKLCH**：按顶栏区域的壁纸亮度求玻璃底色透明度，保证 WCAG 对比度；明暗两套色调由同一调色板生成。
- **概览底层壁纸**：三指上滑第一下（窗口选择器）壁纸模糊 56px、压暗到 0.66；第二下（应用网格）清晰壁纸 + 遮罩。
- **概览缩放回桌面的直线**：GNOME 在整个缩放过程中把工作区卡片的壁纸裁到“屏幕减顶栏”的工作区，圆角也在这条边上；透明顶栏下就成了一条停在顶栏下沿的直线，结束时顶栏那条再突然出现。`WorkspaceClipPatch` 让裁剪区随状态值从工作区平滑长到整屏，卡片四边一起到达屏幕边缘；禁用扩展时恢复 GNOME 原样。
- **扩展 UUID**：原先借用 extensions.gnome.org 上真实存在的 `avatar-quick-settings@github.leginreklaw`，在线更新会把我们的代码覆盖掉。现为 `lumina-shell@lumina-live-wallpaper`（名称 Lumina Shell，保留头像功能）。旧机器上由 `lumina-migrate-uuid.service` 在下次登录、GNOME Shell 启动前一次性切换，旧目录移到 `~/.local/share/lumina-backup/<日期>-old-uuid/`。
- **安装脚本**：原来漏装 `glass.js`（全新安装会导致扩展加载失败）；`gnome-extensions enable` 对尚未被 Shell 加载的扩展无效，安装脚本现直接写入 `enabled-extensions`。

### 6. 2026-11-13 / 14：性能与细节
- **屏幕尺寸、30 fps 的播放副本（`lumina-fit-video`）**：30 fps 限帧发生在解码之后，4K/60 的壁纸在 2736×1824 屏幕上照样每秒解满 60 帧 4K。现在设壁纸时用 GPU（VA-API，失败时退回 x264）转一份刚好盖满屏幕、帧率 ≤ 30 的副本，放在 `~/.local/share/live-wallpaper/fitted/`，记在 `registry.json` 的 `fitted` 里；原文件仍是登记的壁纸。守护进程只在副本仍盖满当前显示器（旋转成竖屏就不行）、原文件未改动、副本没有播放失败时才用它，显示器几何变化时重新判断。4K/60 壁纸只解码：GPU 占用 33–34% → 19%（空闲 4%），GT 平均频率 ~370 → ~90 MHz；与原片同尺寸对比 PSNR 47–50 dB、SSIM 0.991。`set-live-wallpaper --fit-all` 重做全部副本，`--remove` 一并删除。
- **分屏暂停**：见第 1 条「窗口遮挡智能休眠」。
- **概览卡片里的实时壁纸**：GNOME 的工作区卡片画的是静态壁纸，也就是动态壁纸的封面（第一帧），从概览缩回桌面时先停在封面上，再跳到视频当前帧（信件壁纸上雾气、颜色、头发和花瓣都会跳）。现在卡片在静态图之上叠一个视频窗口的实时克隆，由 GLSL 效果按卡片自己的圆角矩形遮罩，缩回桌面时交接的是同一帧。
- **`current-live-wallpaper.mp4` 链接**：原来只有 `set-live-wallpaper` 会更新它，在「设置 → 外观」里切换后它还指着旧壁纸；守护进程又把它当作“找不到对应视频的封面”的兜底，于是会在一张封面上播别的壁纸的视频。现在守护进程每次启用动态壁纸都把链接改指向它（原子替换），没有视频的封面按静态壁纸显示，`--remove` 会删掉悬空的链接。
- **真实桌面实测（2026-11-13，终端最大化、强制视频在其后播放，只有顶栏那条露出视频；单核百分比）**：

  | 情形 | gnome-shell CPU | 守护进程 CPU | GPU 总占用 |
  | :--- | ---: | ---: | ---: |
  | 暂停（基线） | 5.6% | 0% | 12.8% |
  | 屏幕尺寸 30 fps 副本 + 玻璃 | 31.3% | 6.0% | 44.7% |
  | 屏幕尺寸 30 fps 副本，关玻璃 | 17.8% | 6.2% | 43.4% |
  | 原片 3840×2160@60 + 玻璃 | 34.7% | 6.8% | 52.5% |

  换掉 `Clutter.BlurNode` 之前同样“视频 + 玻璃”是 87% 单核，关玻璃 21%。

---

## 三、 系统运行状态与文件部署映射矩阵

### 1. 服务运行状态
```bash
# 查看壁纸守护进程与莫奈服务
systemctl --user status live-wallpaper.service monet-panel.service
```
- `live-wallpaper.service`：视频播放时守护进程本身约 6% 单核，被窗口挡住时 0（2026-11-13 / 14 实测）。
- `monet-panel.service`：只在壁纸或明暗模式变化时工作。

### 2. 核心文件部署与仓库映射表
| 本机实际部署路径 | 代码仓库源文件路径 (`lumina-live-wallpaper`) | 文件说明 |
| :--- | :--- | :--- |
| `~/.local/bin/live-wallpaper-daemon` | `linux/live-wallpaper-daemon` | GStreamer 硬件解码与窗口渲染守护进程 |
| `~/.local/bin/monet-panel.py` | `linux/monet-panel.py` | 莫奈取色引擎与全系统色彩联动生成器（顶栏 CSS 写进扩展目录的 `stylesheet.css`） |
| `~/.local/bin/set-live-wallpaper` | `linux/set-live-wallpaper` | 用户 CLI 快捷工具（支持 `--list`, `--remove`, `--fit-all` 等） |
| `~/.local/bin/lumina-fit-video` → `~/.local/share/live-wallpaper/fitted/` | `linux/lumina-fit-video` | 生成屏幕尺寸、≤ 30 fps 的播放副本，记入 `registry.json` 的 `fitted` |
| `~/.local/share/gnome-shell/extensions/lumina-shell@lumina-live-wallpaper/` | `linux/extension/lumina-shell@lumina-live-wallpaper/` | GNOME Shell 扩展：`extension.js`（头像、窗口遮挡暂停、CSS 热重载）+ `glass.js`（液态玻璃、概览壁纸、概览缩放裁剪） |
| `~/.local/bin/lumina-migrate-uuid` + `~/.config/systemd/user/lumina-migrate-uuid.service` | `linux/lumina-migrate-uuid`, `linux/systemd/lumina-migrate-uuid.service` | 旧 UUID → 新 UUID 的一次性迁移，执行后自行停用 |
| `~/.config/systemd/user/live-wallpaper.service` | `linux/systemd/live-wallpaper.service` | 壁纸服务 systemd 用户单元配置 |
| `~/.config/systemd/user/monet-panel.service` | `linux/systemd/monet-panel.service` | 莫奈服务 systemd 用户单元配置 |
| （不部署） | `dev/preview/` | 隔离的无头 gnome-shell 预览：截图检查顶栏、快捷设置、概览，不影响真实桌面 |

---

## 四、 Git 仓库与本地版本状态

- **仓库根目录**: `~/my-video/lumina-live-wallpaper`
- **分支**：2026-11-14 按用户指示把 `glass-rework` 快进合并进 `main`（`main` 原停在 2026-11-11 的版本）。
- **远程**：`origin` 为 `git@github.com:t0705xl/lumina-live-wallpaper.git`（SSH）。本机连不上 github.com，SSH 通过 `~/.ssh/config` 走本地代理。
- **隐私（2026-11-14）**：推送前改写了全部历史：作者/提交者邮箱换成 GitHub 隐私邮箱 `294123201+t0705xl@users.noreply.github.com`（本仓库 `user.email` 已设为它），本机用户名与路径从所有历史版本中移除（预览调试扩展改名为 `lumina-debug@lumina-live-wallpaper`），随后强制推送。改写前的历史只备份在本机 `~/.local/share/lumina-backup/2026-11-14-before-history-scrub.bundle`，不要推送。

---

## 五、 常用运维与交互指令备忘

```bash
# 1. 切换动态壁纸（自动生成硬链接并更新系统设置）
set-live-wallpaper ~/.local/share/backgrounds/your-video.mp4

# 2. 列出当前所有已注册的动态壁纸
set-live-wallpaper --list

# 2b. 重新生成所有壁纸的屏幕尺寸播放副本（换了显示器分辨率后用）
set-live-wallpaper --fit-all

# 3. 手动重新提取当前壁纸的莫奈色并注入系统
python3 ~/.local/bin/monet-panel.py

# 4. 顶栏样式：monet-panel 写入 stylesheet.css 后扩展会自动热重载，无需开关扩展
#    改了 extension.js / glass.js 则需要注销重新登录（Wayland 下无法重启 Shell）

# 5. 不注销预览：隔离的无头 GNOME Shell + 截图（输出在 ~/.cache/lumina-preview/run/lumina-debug/）
dev/preview/preview.sh shoot <壁纸路径> prefer-dark <标签>
dev/preview/preview.sh menu overview | appGrid | desktop | state:0.3   # state: 把概览冻结在缩放中途
dev/preview/preview.sh shot <名字>; dev/preview/preview.sh stop
X11=1 WP_URI=file://...-cover.png dev/preview/preview.sh start; dev/preview/preview.sh live   # 在预览里跑真实壁纸守护进程

# 6. 玻璃性能基准：真实分辨率预览 + 30 fps 动态背景，测预览 Shell 的 CPU/帧率/GPU
PREVIEW_SIZE=2736x1824 dev/preview/preview.sh start prefer-dark
DBUS_SESSION_BUS_ADDRESS=$(cat ~/.cache/lumina-preview/bus) python3 dev/preview/scale.py 2
python3 dev/preview/bench.py 20 idle noglass glass
```

---

## 六、 阶段交接与后续建议 (Next Steps)

1. **如接力人（Argon 或其他开发者）需要继续扩展**：
   - 当前底层（GStreamer 限帧解码、硬链接设置同步、莫奈取色、顶栏液态玻璃）已经形成稳定闭环，架构极为干净。
   - 后续可着眼于高层应用层功能，如：在快捷设置面板中添加“一键切换动态壁纸”开关，或开发一个图形化壁纸选择器前端。
2. **远程推送**：
   - 已于 2026-11-14 推送 `main`；以后在 `main` 上直接提交并 `git push` 即可。提交前确认 `git config user.email` 仍是隐私邮箱。
3. **已知问题与状态（2026-11-13 / 14）**：
   - **玻璃在视频播放时很贵 → 已优化并已在真实桌面复测**：真实桌面实测 gnome-shell 主线程 CPU，视频播放 + 玻璃 87% 单核，关掉玻璃 21%。原因是 `Clutter.BlurNode` 每个胶囊每帧都重新分配纹理和帧缓冲（预览里单它就占每帧 13.5 ms 中的 9.2 ms）。现改为自写的两遍高斯模糊，纹理只在尺寸变化时重建，CSS 参数按 `style-changed` 缓存：预览（2736×1824、200%、30 fps 动态背景，`dev/preview/bench.py`）中开玻璃每帧 CPU 13.5 ms → 2.4 ms，关玻璃为 1.3 ms；画面与旧版逐像素对比差异 ≤ 2/255。真实桌面复测：gnome-shell 87% → 31% 单核（关玻璃 18%），见第二节第 6 条的表格。
   - **耗电瓦数未测到**：测试时插着电源（状态为 Charging），电池功率读数是充电功率，作废；需要拔电再测一次。
   - **退出概览时的画面跳变 → 已修复**：在预览里跑真实守护进程确认了确实会跳（卡片显示封面，桌面是视频当前帧），现在卡片里叠了实时视频克隆，见第二节第 6 条。
   - **待办**：拔掉电源测一次功耗瓦数；壁纸守护进程只看主显示器，多显示器未适配。
