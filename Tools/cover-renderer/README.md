# Arkgram 版本封面渲染器

使用离线保存的 Rahoo `coverC` 模板生成 `1146x797` 的版本更新封面。
渲染器只依赖本机 Python 3、Node.js 和 Chrome/Chromium，不访问外网。

## 安装

```bash
npm ci --prefix Tools/cover-renderer --ignore-scripts --no-audit --no-fund
```

Chrome 会自动从常见安装路径查找；特殊安装位置可设置 `CHROME_BIN`。

## 命令行

```bash
node Tools/cover-renderer/render-cover.mjs \
  --version 13.0.2 \
  --detail bfueiw \
  --output /tmp/Arkgram-cover.png
```

- `--version`：大版本号，对应画布右侧的版本文字。
- `--detail`：右上角的 commit 短 SHA。
- `--output`：PNG 输出路径。

`config.json` 保存模板中的固定文字、两张立绘、缩放和位置。GitHub Actions
的 `upload.py` 会自动读取 `gradle.properties` 的 `APP_VERSION_NAME` 和当前
`COMMIT_ID` 短 SHA，生成封面并作为 Telegram 相册首图发送。
