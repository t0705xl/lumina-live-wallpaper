# Lumina Live Wallpaper & Monet Desktop System
## 阶段交接报告与人物/任务现状 (Handover & Status Report)

- **生成时间**: 2026-11-11（2026-11-13 更新：自绘液态玻璃、独立扩展 UUID、概览缩放修复，见第二节第 5 条与第六节）
- **运行平台**: Microsoft Surface Pro 7+ (Fedora 44 / Linux 6.19 / GNOME 50 Wayland，2736×1824，缩放 200%)
- **代码仓库**: `~/my-video/lumina-live-wallpaper`（2026-11-13 的改动在分支 `glass-rework`，未合并、未推送）
- **系统核心服务**: `live-wallpaper.service` | `monet-panel.service`

---

## 一、 人物与角色分工现状 (Roles & Ownership)

| 角色 / 人物代号 | 负责阶段 | 核心权责与工作范畴 | 当前交付状态 |
| :--- | :--- | :--- | :--- |
| **Argon (架构与原型)** | 阶段一：奠基与架构建立 | 搭建 GStreamer 基础管线、设计 GJS 顶栏扩展原型、初步规划 Material You 取色原型与守护进程体系。 | 已完成初期架构设计，并平稳交接。 |
| **Antigravity (当前调优者)** | 阶段二：本土化痛点攻坚与视觉重构 | 针对 Surface Pro 7+ 与 GNOME 50 环境：<br>1. 硬件级 30fps 限帧与多媒体功耗大幅压降；<br>2. 莫奈色彩直方图聚类重构（根治红信件偏色）；<br>3. 规避 GNOME 设置面板 `NOFOLLOW_SYMLINKS` 缺陷（硬链接方案）；<br>4. 状态栏液态玻璃去雾、去发白内阴影，修复 `RENAMED` 样式热重载失效漏洞。 | 本阶段任务全部交付并完成本地 Git 归档，随时可由 Argon 或下一负责人接力。 |
| **Claude Code (2026-11-13)** | 阶段二续：玻璃重做与稳固 | 自绘圆角背景模糊 `glass.js`、OKLCH 取色与 WCAG 对比度求解、概览底层壁纸、扩展迁出借用的 UUID、安装脚本修复、无头预览工具 `dev/preview`。 | 已提交到 `glass-rework` 分支，等待用户验收。 |
| **Next Maintainer (接班维护者)** | 阶段三：长效演进（待办建议） | 多显示器环境适配、壁纸自动轮播策略、打包 RPM/Flatpak 发行版、视用户指令决定是否向远程 GitHub 仓库推送代码。 | 待启动 |

---

## 二、 核心技术攻坚成果与指标对比

### 1. 性能、功耗与能效优化
- **30fps 硬件帧率约束**：接入 GStreamer `videorate (drop-only=true, max-rate=30)`，彻底消除了 Surface Pro 7+ 移动核显多余的高刷负载。
  - **单核 CPU 占用**：由 **11.6%** 骤降并稳态锁定在 **4.5%**（降幅达 **61.2%**）。
  - **内存表现**：稳态内存驻留 ~540MB，且全程无内存泄漏。
- **动态平滑过渡**：两段视频壁纸切换时，引入 `opacity: 0.24` 微降过渡，彻底消除了壁纸切换时的黑场闪烁感。
- **全屏/最大化智能休眠**：在 GJS 扩展中监听窗口覆盖率与 `Maximized` 状态，当常规窗口遮挡面积 $\ge 94\%$ 时自动暂停视频解码；休眠时自动挂起，唤醒时自动重载自愈。

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

---

## 三、 系统运行状态与文件部署映射矩阵

### 1. 服务运行状态
```bash
# 查看壁纸守护进程与莫奈服务
systemctl --user status live-wallpaper.service monet-panel.service
```
- `live-wallpaper.service`：视频播放时守护进程本身约 3–7% 单核（2026-11-13 实测）。
- `monet-panel.service`：只在壁纸或明暗模式变化时工作。

### 2. 核心文件部署与仓库映射表
| 本机实际部署路径 | 代码仓库源文件路径 (`lumina-live-wallpaper`) | 文件说明 |
| :--- | :--- | :--- |
| `~/.local/bin/live-wallpaper-daemon` | `linux/live-wallpaper-daemon` | GStreamer 硬件解码与窗口渲染守护进程 |
| `~/.local/bin/monet-panel.py` | `linux/monet-panel.py` | 莫奈取色引擎与全系统色彩联动生成器（顶栏 CSS 写进扩展目录的 `stylesheet.css`） |
| `~/.local/bin/set-live-wallpaper` | `linux/set-live-wallpaper` | 用户 CLI 快捷工具（支持 `--list`, `--remove` 等） |
| `~/.local/share/gnome-shell/extensions/lumina-shell@lumina-live-wallpaper/` | `linux/extension/lumina-shell@lumina-live-wallpaper/` | GNOME Shell 扩展：`extension.js`（头像、窗口遮挡暂停、CSS 热重载）+ `glass.js`（液态玻璃、概览壁纸、概览缩放裁剪） |
| `~/.local/bin/lumina-migrate-uuid` + `~/.config/systemd/user/lumina-migrate-uuid.service` | `linux/lumina-migrate-uuid`, `linux/systemd/lumina-migrate-uuid.service` | 旧 UUID → 新 UUID 的一次性迁移，执行后自行停用 |
| `~/.config/systemd/user/live-wallpaper.service` | `linux/systemd/live-wallpaper.service` | 壁纸服务 systemd 用户单元配置 |
| `~/.config/systemd/user/monet-panel.service` | `linux/systemd/monet-panel.service` | 莫奈服务 systemd 用户单元配置 |
| （不部署） | `dev/preview/` | 隔离的无头 gnome-shell 预览：截图检查顶栏、快捷设置、概览，不影响真实桌面 |

---

## 四、 Git 仓库与本地版本状态

- **仓库根目录**: `~/my-video/lumina-live-wallpaper`
- **分支**：`main` 停在 2026-11-11 的版本；2026-11-13 的改动全部在 `glass-rework`（`git log main..glass-rework` 查看），用户验收后再合并。
- **远程**：`origin` 指向 GitHub，遵照用户约束**未执行远程 push**。

---

## 五、 常用运维与交互指令备忘

```bash
# 1. 切换动态壁纸（自动生成硬链接并更新系统设置）
set-live-wallpaper ~/.local/share/backgrounds/your-video.mp4

# 2. 列出当前所有已注册的动态壁纸
set-live-wallpaper --list

# 3. 手动重新提取当前壁纸的莫奈色并注入系统
python3 ~/.local/bin/monet-panel.py

# 4. 顶栏样式：monet-panel 写入 stylesheet.css 后扩展会自动热重载，无需开关扩展
#    改了 extension.js / glass.js 则需要注销重新登录（Wayland 下无法重启 Shell）

# 5. 不注销预览：隔离的无头 GNOME Shell + 截图（输出在 ~/.cache/lumina-preview/run/lumina-debug/）
dev/preview/preview.sh shoot <壁纸路径> prefer-dark <标签>
dev/preview/preview.sh menu overview | appGrid | desktop | state:0.3   # state: 把概览冻结在缩放中途
dev/preview/preview.sh shot <名字>; dev/preview/preview.sh stop

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
   - 当用户确认需要同步到 GitHub 远程仓库时，先把 `glass-rework` 合并进 `main`，再 `git push origin main`。
3. **已知问题（2026-11-13 实测）**：
   - **玻璃在视频播放时很贵 → 已优化**：真实桌面实测 gnome-shell 主线程 CPU，视频播放 + 玻璃 87% 单核，关掉玻璃 21%。原因是 `Clutter.BlurNode` 每个胶囊每帧都重新分配纹理和帧缓冲（预览里单它就占每帧 13.5 ms 中的 9.2 ms）。现改为自写的两遍高斯模糊，纹理只在尺寸变化时重建，CSS 参数按 `style-changed` 缓存：预览（2736×1824、200%、30 fps 动态背景，`dev/preview/bench.py`）中开玻璃每帧 CPU 13.5 ms → 2.4 ms，关玻璃为 1.3 ms；画面与旧版逐像素对比差异 ≤ 2/255。真实桌面上的新数字待用户重新加载后复测。
   - **耗电瓦数未测到**：测试时插着电源（状态为 Charging），电池功率读数是充电功率，作废；需要拔电再测一次。
   - **退出概览时可能的画面跳变（读代码推测，未实测）**：概览里的卡片显示静态封面，桌面上是视频当前帧，退出概览时两者可能对不上。
