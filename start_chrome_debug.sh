#!/bin/bash
# mac 端启动 Chrome 调试实例 (9222 端口, 自动化专属用户数据目录)
# 用法: ./start_chrome_debug.sh [可选: 启动后打开的网址]

USER_DATA="$HOME/ChromeDebugUser"
mkdir -p "$USER_DATA"

CHROME_PATH=""
for p in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "$HOME/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; do
  if [ -x "$p" ]; then
    CHROME_PATH="$p"
    break
  fi
done

if [ -z "$CHROME_PATH" ]; then
  echo "[ERROR] 未找到 Google Chrome，请确认已安装！"
  exit 1
fi

URL="${1:-https://www.dianxiaomi.com/web/amazon/add}"

echo "Starting Chrome with remote debugging on port 9222..."
echo "用户数据目录: $USER_DATA"
"$CHROME_PATH" --remote-debugging-port=9222 --user-data-dir="$USER_DATA" \
  --no-first-run --no-default-browser-check "$URL" &

echo "Chrome launched successfully on port 9222!"
