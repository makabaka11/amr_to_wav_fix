# AMR to WAV Fix

修复 NapCat AMR 语音无法被 STT 识别的问题，自动使用 ffmpeg 转换为 WAV。

## 功能

- 自动拦截 STT 处理前的消息链，检测 AMR 格式语音
- 使用 ffmpeg 将 AMR 转换为 16kHz 单声道 PCM WAV，兼容主流 STT 引擎
- 支持多种文件来源：本地路径、HTTP 链接、base64 编码、NapCat `file`+`url` 回退
- 插件启停自动管理临时文件，禁用时恢复原始处理逻辑

## 依赖

| 依赖 | 说明 |
|------|------|
| [AstrBot](https://github.com/AstrBotDevs/AstrBot) | 插件运行平台 |
| ffmpeg | 音频格式转换工具，**必须安装并加入系统 PATH** |

### 安装 ffmpeg

**Windows**

1. 从 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 下载 `ffmpeg-release-essentials.zip`
2. 解压到任意目录（如 `C:\ffmpeg`）
3. 将 `C:\ffmpeg\bin` 添加到系统环境变量 PATH
4. 重启终端，运行 `ffmpeg -version` 验证

**macOS**

```bash
brew install ffmpeg
```

**Linux (Debian/Ubuntu)**

```bash
sudo apt update && sudo apt install ffmpeg
```

**Linux (CentOS/RHEL)**

```bash
sudo yum install epel-release
sudo yum install ffmpeg
```

安装完成后运行 `ffmpeg -version`，确认输出版本信息即表示安装成功。

## 安装插件

将本仓库克隆到 AstrBot 插件目录：

```bash
cd C:\Users\用户名\.astrbot\data\plugins
git clone https://github.com/makabaka11/amr_to_wav_fix.git
```

重启 AstrBot 或在管理面板中启用插件即可。

## 工作原理

1. 插件初始化时 monkey-patch `PreProcessStage.process` 方法
2. 收到语音消息时，通过文件头 magic bytes (`#!AMR\n`) 判断是否为 AMR 格式
3. 调用 ffmpeg 将 AMR 转为 WAV，替换消息链中的文件路径
4. 原始 `process` 方法继续执行 STT 识别流程
5. 插件禁用时自动恢复原始方法并清理临时文件

## 许可证

MIT
