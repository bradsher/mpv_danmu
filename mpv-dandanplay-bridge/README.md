# MPV 弹弹play弹幕桥接插件

一个面向个人本地媒体库的 MPV 插件：打开本地视频后，自动调用弹弹play开放弹幕网络识别剧集、按需获取弹幕、缓存结果并转换为 ASS 字幕加载到 MPV。

它不含公共 Key、不经由公共代理，也不做批量抓取。每个用户在自己的电脑上配置自己的 `AppId` / `AppSecret`。

## 功能

- 文件前 16 MiB MD5 + 文件名自动匹配节目；
- 自动获取并缓存弹幕；已匹配文件不会反复搜索；
- 缓存的弹幕默认 24 小时内不重复下载；
- 自动匹配失败时，按 `Ctrl+d` 根据当前文件名搜索候选剧集，再按数字键选择；
- `Ctrl+Shift+d` 强制重新匹配并刷新弹幕；
- 不需要 `requests`、`curl`、uosc 或第三方 Python 包。

离线验证可直接运行：`python -m unittest discover -s tests -v`。

## 依赖

- MPV 0.34+；
- Python 3.9+，并且命令行中 `python --version` 能正常工作；
- 已获批的弹弹play开放弹幕网络 `AppId` 和 `AppSecret`。

Windows 一般直接安装 [Python](https://www.python.org/downloads/) 并勾选 **Add python.exe to PATH** 即可。若你的系统命令为 `python3`，请改用下面的脚本选项。

## 安装

以下以 Windows 的便携版 MPV 为例。若你的配置目录是 `%APPDATA%\mpv`，把相同文件放进该目录即可。

1. 下载本项目并把整个目录复制为：

   ```text
   <mpv目录>\portable_config\scripts\dandanplay_bridge\
   ```

2. 在这个目录内复制并改名：

   ```text
   dandanplay_bridge.example.json  ->  dandanplay_bridge.json
   ```

   打开 `dandanplay_bridge.json`，填写你的 `app_id` 和 `app_secret`。这个文件已被 `.gitignore` 忽略，**绝不能上传到 GitHub**。

3. 在 `portable_config\mpv.conf` 追加一行，明确加载脚本：

   ```text
   scripts=~~/scripts/dandanplay_bridge/dandanplay_bridge.lua
   ```

4. 可选：复制 `script-opts.example.conf` 到：

   ```text
   <mpv目录>\portable_config\script-opts\dandanplay_bridge.conf
   ```

   如果 `python --version` 无法工作而 `python3 --version` 可以，把 `python_command=python` 改为 `python_command=python3`。

5. 用 MPV 打开一个本地视频。首次播放会自动尝试匹配并加载弹幕。

## 使用

| 操作 | 默认方式 |
| --- | --- |
| 自动识别并加载 | 打开本地视频 |
| 搜索候选剧集 | `Ctrl+d` |
| 选择候选集 | 搜索结果出现后按 `1` 至 `9` |
| 强制刷新 | `Ctrl+Shift+d` |
| 指定手动搜索词 | MPV 控制台执行 `script-message dandanplay-search 剧名` |

插件只处理本地文件，不处理网络视频 URL。自动匹配使用当前文件名与前 16 MiB 的 MD5；如果字幕组命名奇怪、视频被重封装或识别到了错误剧集，用 `Ctrl+d` 手动选择即可。

## 配置说明

`dandanplay_bridge.json` 中常用的选项：

| 字段 | 默认值 | 作用 |
| --- | --- | --- |
| `comment_cache_ttl_hours` | `24` | 同一集弹幕多久后才重新下载；设为 `0` 可关闭弹幕缓存。 |
| `font_name` | `Microsoft YaHei` | ASS 弹幕字体。 |
| `font_size` | `38` | 以 1920×1080 基准的字号。 |
| `scroll_duration` | `8` | 滚动弹幕横穿画面所需秒数。 |
| `max_comments` | `12000` | 单集最多加载的弹幕条数，避免极高密度视频拖慢播放器。 |

`script-opts/dandanplay_bridge.conf` 中：

| 字段 | 默认值 | 作用 |
| --- | --- | --- |
| `python_command` | `python` | Python 可执行文件名或路径。 |
| `auto_load` | `yes` | 打开文件后自动请求；设为 `no` 时只在手动快捷键触发。 |
| `load_delay_seconds` | `1` | MPV 加载媒体后等待多久再开始请求。 |

## 隐私、缓存和 API 使用

- 只在实际打开本地视频或手动搜索时请求 API；
- 文件识别结果与弹幕只保存在本地 `cache/`；
- 不上传视频内容：用于识别的只是文件名与本地计算出的 MD5；
- 不提供公共代理，不批量遍历媒体库，不下载弹幕数据库；
- 请遵守弹弹play开放弹幕网络的缓存和按需调用要求。

弹弹play官方文档建议客户端使用签名验证模式；本项目每次请求都以 `AppId + Timestamp + API Path + AppSecret` 计算 SHA-256/Base64 签名，密钥只读取本机的私有配置文件。

## 用于开放平台申请的项目描述

> 本项目是供个人使用的 MPV 本地媒体弹幕加载插件。用户使用 MPV 打开本地视频时，插件根据文件名和文件前16MB的 MD5 调用文件识别接口；自动识别失败时，用户可以手动搜索并选择节目；确认节目后，插件按需获取弹幕、转换为 ASS 字幕并加载到播放器。识别结果和弹幕均在本地缓存，避免重复请求。项目不提供公共代理，不进行批量抓取、数据库下载或商业化运营，应用凭证仅存放于个人设备的忽略配置文件中。

## License

MIT
