# Lumina Live Wallpaper & Monet Desktop System
## 阶段交接报告与人物/任务现状 (Handover & Status Report)

- **生成时间**: 2026-11-11
- **运行平台**: Microsoft Surface Pro 7+ (Fedora 44 / Linux 6.18+ / GNOME 50 Wayland)
- **代码仓库**: `~/my-video/lumina-live-wallpaper` (Git Branch: `main`)
- **系统核心服务**: `live-wallpaper.service` (PID: 14650) | `monet-panel.service` (PID: 14647)

---

## 一、 人物与角色分工现状 (Roles & Ownership)

| 角色 / 人物代号 | 负责阶段 | 核心权责与工作范畴 | 当前交付状态 |
| :--- | :--- | :--- | :--- |
| **Argon (架构与原型)** | 阶段一：奠基与架构建立 | 搭建 GStreamer 基础管线、设计 GJS 顶栏扩展原型、初步规划 Material You 取色原型与守护进程体系。 | 已完成初期架构设计，并平稳交接。 |
| **Antigravity (当前调优者)** | 阶段二：本土化痛点攻坚与视觉重构 | 针对 Surface Pro 7+ 与 GNOME 50 环境：<br>1. 硬件级 30fps 限帧与多媒体功耗大幅压降；<br>2. 莫奈色彩直方图聚类重构（根治红信件偏色）；<br>3. 规避 GNOME 设置面板 `NOFOLLOW_SYMLINKS` 缺陷（硬链接方案）；<br>4. 状态栏液态玻璃去雾、去发白内阴影，修复 `RENAMED` 样式热重载失效漏洞。 | 本阶段任务全部交付并完成本地 Git 归档，随时可由 Argon 或下一负责人接力。 |
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

---

## 三、 系统运行状态与文件部署映射矩阵

### 1. 服务运行状态
```bash
# 查看壁纸守护进程与莫奈服务
systemctl --user status live-wallpaper.service monet-panel.service
```
- `live-wallpaper.service`: `active (running)`, PID 14650, 稳态单核 CPU ~4.5%。
- `monet-panel.service`: `active (running)`, PID 14647, 内存 ~22MB。

### 2. 核心文件部署与仓库映射表
| 本机实际部署路径 | 代码仓库源文件路径 (`lumina-live-wallpaper`) | 文件说明 |
| :--- | :--- | :--- |
| `~/.local/bin/live-wallpaper-daemon` | `daemon/live-wallpaper-daemon` | GStreamer 硬件解码与窗口渲染守护进程 |
| `~/.local/bin/monet-panel.py` | `linux/monet-panel.py` | 莫奈取色引擎与全系统色彩联动生成器 |
| `~/.local/bin/set-live-wallpaper` | `cli/set-live-wallpaper` | 用户 CLI 快捷工具（支持 `--list`, `--remove` 等） |
| `~/.local/share/gnome-shell/extensions/avatar-quick-settings@github.leginreklaw/` | `linux/extension/avatar-quick-settings@github.leginreklaw/` | GNOME Shell 扩展（负责液态玻璃、头像、窗口遮挡暂停、无缝 CSS 热重载） |
| `~/.config/systemd/user/live-wallpaper.service` | `linux/systemd/live-wallpaper.service` | 壁纸服务 systemd 用户单元配置 |
| `~/.config/systemd/user/monet-panel.service` | `linux/systemd/monet-panel.service` | 莫奈服务 systemd 用户单元配置 |

---

## 四、 Git 仓库与本地版本状态

- **仓库根目录**: `~/my-video/lumina-live-wallpaper`
- **当前最新提交**:
  ```text
  commit 331f5f4bfa55bb05d4dfc80cf55cae72ebdf0b5b
  Author: EzBsk
  Date:   Wed Nov 11 08:13:40 2026 -0600

      fix(panel): eliminate cloudy fog band on top pills and fix stylesheet hot-reload in extension
  ```
- **远程分支状态**: `origin/main` 暂未建立同步，遵照用户约束**未执行远程 push**，所有成果均已完整保存在本地 Git 树中。

---

## 五、 常用运维与交互指令备忘

```bash
# 1. 切换动态壁纸（自动生成硬链接并更新系统设置）
set-live-wallpaper ~/.local/share/backgrounds/your-video.mp4

# 2. 列出当前所有已注册的动态壁纸
set-live-wallpaper --list

# 3. 手动重新提取当前壁纸的莫奈色并注入系统
python3 ~/.local/bin/monet-panel.py

# 4. 强制无闪烁刷新 GNOME Shell 顶栏液态玻璃样式
gdbus call --session --dest org.gnome.Shell.Extensions --object-path /org/gnome/Shell/Extensions --method org.gnome.Shell.Extensions.DisableExtension "avatar-quick-settings@github.leginreklaw"
sleep 0.2
gdbus call --session --dest org.gnome.Shell.Extensions --object-path /org/gnome/Shell/Extensions --method org.gnome.Shell.Extensions.EnableExtension "avatar-quick-settings@github.leginreklaw"
```

---

## 六、 阶段交接与后续建议 (Next Steps)

1. **如接力人（Argon 或其他开发者）需要继续扩展**：
   - 当前底层（GStreamer 限帧解码、硬链接设置同步、莫奈取色、顶栏液态玻璃）已经形成稳定闭环，架构极为干净。
   - 后续可着眼于高层应用层功能，如：在快捷设置面板中添加“一键切换动态壁纸”开关，或开发一个图形化壁纸选择器前端。
2. **远程推送**：
   - 当用户确认需要同步到 GitHub 远程仓库时，只需执行 `git push origin main` 即可。
