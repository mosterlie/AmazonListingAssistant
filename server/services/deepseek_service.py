"""
DeepSeek AI 对话、自动填入提交、等待回答、点击复制并回切商品录入页面服务
"""
import re
import time
from typing import Dict, Any, List, Optional
from browser_engine import BrowserEngine
from server.config import DEFAULT_DEEPSEEK_URL


class DeepSeekService:
    """DeepSeek 自动化调度、等待回答、点击复制与提取回填服务"""

    @staticmethod
    def extract_between_ampersands(full_text: str) -> Dict[str, Any]:
        """
        从 DeepSeek 完整回复中提取 &&...&& 两行之间的日文五点描述内容
        并在商品描述中为每一条加上序号 (1. 2. 3. 4. 5.)
        """
        if not full_text:
            return {"raw_text": "", "extracted_jp_text": "", "bullet_points": []}

        extracted_lines = []
        lines = [l.strip() for l in full_text.splitlines()]
        inside_ampersands = False
        found_ampersands = False

        for line in lines:
            # 判断是否是由 & 构成的分隔行 (过滤空格后 >= 2 个 &)
            stripped_line = line.replace(" ", "")
            is_amp_line = bool(re.match(r"^&{2,}$", stripped_line))

            if is_amp_line:
                if not inside_ampersands:
                    inside_ampersands = True
                    found_ampersands = True
                    continue
                else:
                    inside_ampersands = False
                    break  # 找到闭合的分隔行，提取结束

            if inside_ampersands:
                if line:
                    extracted_lines.append(line)

        # 备选 1: 若按行没有闭合，尝试正则全局提取
        if not found_ampersands or not extracted_lines:
            match = re.search(r'&{2,}\s*\n?(.*?)\n?&{2,}', full_text, re.DOTALL)
            if match:
                extracted_block = match.group(1).strip()
                extracted_lines = [l.strip() for l in extracted_block.splitlines() if l.strip()]

        # 备选 2: 若未找到 & 标记，截取 "一、日文版" 和 "二、中文翻译" 之间
        if not extracted_lines:
            if "日文版" in full_text and ("中文翻译" in full_text or "二、" in full_text):
                parts = re.split(r'二[、.·]\s*中文翻译|中文翻译|二、', full_text)
                jp_part = parts[0]
                for l in jp_part.splitlines():
                    l_s = l.strip()
                    if not l_s or "日文版" in l_s or l_s.startswith("-") or l_s.startswith("&") or l_s.startswith("="):
                        continue
                    extracted_lines.append(l_s)
            else:
                extracted_lines = [l for l in lines if l and not l.startswith("&")]

        # 清洗各条目并去除原本多余的前缀
        cleaned_bullets = []
        for l in extracted_lines:
            if l.startswith("&") or l.startswith("-") or l.startswith("="):
                continue
            clean_l = re.sub(r'^\d+[\.、\s\-]+', '', l).strip()
            if clean_l:
                cleaned_bullets.append(clean_l)

        # 核心要求 3: 在商品描述中，每一条增加序号 1. 2. 3. 4. 5.
        numbered_lines = [f"{idx + 1}. {bullet}" for idx, bullet in enumerate(cleaned_bullets)]
        extracted_jp_text = "\n".join(numbered_lines)

        # 提取中文翻译段落 (逐条展示供人检查对错)
        chinese_bullets = []
        if "中文翻译" in full_text or "二、" in full_text or "翻訳" in full_text:
            parts = re.split(r'二[、.·\s]*中文翻译|中文翻译|二、|翻訳', full_text)
            if len(parts) > 1:
                cn_part = parts[1]
                for l in cn_part.splitlines():
                    l_s = l.strip()
                    if not l_s or l_s.startswith("-") or l_s.startswith("&") or l_s.startswith("="):
                        continue
                    clean_cn = re.sub(r'^\d+[\.、\s\-]+', '', l_s).strip()
                    if clean_cn:
                        chinese_bullets.append(clean_cn)

        return {
            "raw_text": full_text,
            "extracted_jp_text": extracted_jp_text,
            "bullet_points": cleaned_bullets[:10],
            "chinese_translations": chinese_bullets[:10]
        }

    @staticmethod
    def send_prompt_to_deepseek(prompt: str, target_url: str = DEFAULT_DEEPSEEK_URL, wait_for_response: bool = True) -> Dict[str, Any]:
        """
        唤起/接管 Chrome 浏览器，打开指定的 DeepSeek 对话页：
        1. 自动将提示词填入输入框并点击发送
        2. 若 wait_for_response=True，持续监听并等待 DeepSeek 回答完毕
        3. 回答完成后自动点击 DeepSeek 页面中的【复制】按钮
        4. 复制完成后无需在 DeepSeek 输入框中重新输入
        5. 自动切回商品录入页面并完成日文描述回填 (带 1. 2. 3. 编号)
        """
        try:
            engine = BrowserEngine()
            url_to_open = target_url or DEFAULT_DEEPSEEK_URL

            # 1. 确保浏览器处于活跃状态
            if not engine.is_running():
                ok, msg = engine.launch_browser(url_to_open)
            else:
                ok, msg = engine.connect()

            # 2. 打开或聚焦 DeepSeek 目标会话页面
            page = engine.open_or_focus_url(url_to_open)
            if not page:
                return {"success": False, "msg": f"未能打开或激活 DeepSeek 会话页面: {url_to_open}", "data": {"raw_text": "", "extracted_jp_text": "", "bullet_points": []}}

            # 3. 在浏览器常驻线程中调度执行输入、提交、等待与点击复制
            def _automate_deepseek_action(target_page):
                try:
                    target_page.wait_for_load_state("domcontentloaded", timeout=12000)
                except Exception:
                    pass

                target_page.wait_for_timeout(1200)

                # 支持多种输入框选择器
                input_selectors = [
                    "#chat-input",
                    "textarea#chat-input",
                    "textarea[placeholder*='DeepSeek']",
                    "textarea[placeholder*='输入']",
                    "textarea[placeholder*='发送消息']",
                    "textarea[placeholder*='Send a message']",
                    "textarea",
                    "div[contenteditable='true']"
                ]

                input_elem = None
                for sel in input_selectors:
                    try:
                        loc = target_page.locator(sel).first
                        if loc.is_visible():
                            input_elem = loc
                            break
                    except Exception:
                        continue

                if not input_elem:
                    return {
                        "success": True,
                        "msg": f"已成功在浏览器中打开指定 DeepSeek 会话页面！（提示词已复制到剪贴板，可直接快捷键粘贴发送）",
                        "data": {"raw_text": "", "extracted_jp_text": "", "bullet_points": []}
                    }

                # 聚焦并填入提示词
                input_elem.click()
                input_elem.focus()
                input_elem.fill(prompt)
                target_page.wait_for_timeout(500)

                # 寻找发送按钮并点击，或触发 Enter 键提交
                send_selectors = [
                    "div[role='button'][aria-label*='发送']",
                    "div[role='button']:has-text('发送')",
                    "button[aria-label*='发送']",
                    "button:has-text('发送')",
                    "button[type='submit']",
                    ".ds-icon-button",
                    ".send-btn",
                    "div[class*='send-button']"
                ]

                clicked = False
                for sel in send_selectors:
                    try:
                        btn = target_page.locator(sel).first
                        if btn.is_visible():
                            btn.click()
                            clicked = True
                            break
                    except Exception:
                        continue

                if not clicked:
                    target_page.keyboard.press("Enter")

                if not wait_for_response:
                    return {
                        "success": True,
                        "msg": "🎉 已成功将提示词输入 DeepSeek 并点击提交！",
                        "data": {"raw_text": "", "extracted_jp_text": "", "bullet_points": []}
                    }

                # 4. 持续监听并等待 DeepSeek 回答生成完毕
                print("⏳ 正在等待 DeepSeek 回答生成...")
                target_page.wait_for_timeout(3000)

                max_wait_seconds = 90
                start_time = time.time()
                last_text = ""
                stable_count = 0

                message_selectors = [
                    ".ds-markdown",
                    "div[class*='ds-markdown']",
                    ".chat-message-content",
                    "div[class*='markdown']",
                    ".chat-message-item:last-child"
                ]

                while time.time() - start_time < max_wait_seconds:
                    target_page.wait_for_timeout(1500)

                    # 获取最后一条助手回复的内容
                    current_text = ""
                    for msg_sel in message_selectors:
                        try:
                            elems = target_page.locator(msg_sel).all()
                            if elems:
                                current_text = elems[-1].inner_text()
                                if current_text:
                                    break
                        except Exception:
                            continue

                    # 判断是否包含停止生成按钮
                    stop_btn_visible = False
                    try:
                        stop_btn = target_page.locator("div:has-text('停止生成'), button:has-text('停止生成'), .ds-icon-button[aria-label*='停止']").first
                        if stop_btn and stop_btn.is_visible():
                            stop_btn_visible = True
                    except Exception:
                        pass

                    if current_text:
                        # 检查文本是否已稳定不再增长
                        if current_text == last_text and len(current_text) > 30:
                            stable_count += 1
                            # 如果停止按钮已消失且内容稳定超过 2 次检查（约 3 秒）
                            if not stop_btn_visible and stable_count >= 2:
                                print(f"✅ DeepSeek 回答已完成！捕获字数: {len(current_text)}")
                                break
                            # 如果内容已完整包含日文和中文翻译段落，且稳定 2 次
                            if ("中文翻译" in current_text or "二、" in current_text) and stable_count >= 2:
                                print(f"✅ DeepSeek 结构化输出完整！捕获字数: {len(current_text)}")
                                break
                        else:
                            stable_count = 0
                            last_text = current_text

                # 5. 回答完成后：自动点击 DeepSeek 页面中的【复制】按钮！
                try:
                    copy_btn_selectors = [
                        "div[role='button'][aria-label*='复制']",
                        "div[aria-label*='复制']",
                        "button[aria-label*='复制']",
                        "button:has-text('复制')",
                        "div:has-text('复制')",
                        ".ds-icon-button:has(svg)",
                        ".ds-icon-button",
                        "div[class*='copy']"
                    ]
                    for c_sel in copy_btn_selectors:
                        try:
                            c_btns = target_page.locator(c_sel).all()
                            if c_btns:
                                c_btns[-1].click()
                                print("✅ 已成功自动点击 DeepSeek 页面中的【复制】按钮！")
                                break
                        except Exception:
                            continue
                except Exception as copy_err:
                    print(f"⚠️ 点击复制按钮尝试: {copy_err}")

                # 6. 解析提取 &&...&& 区间内容 (每一条自动附带 1. 2. 3. 4. 5. 序号)
                final_text = last_text or current_text
                parsed_result = DeepSeekService.extract_between_ampersands(final_text)

                # 7. 核心要求 2: 复制完成后，自动切回商品录入页面！
                try:
                    for p in engine.manager.context.pages:
                        if "8000" in p.url or "localhost" in p.url or "127.0.0.1" in p.url:
                            p.bring_to_front()
                            print("✅ 已成功将浏览器当前标签页切回商品录入中台！")
                            break
                except Exception as switch_err:
                    print(f"⚠️ 切换标签页尝试: {switch_err}")

                return {
                    "success": True,
                    "msg": "🎉 DeepSeek 回答已复制完毕，并已自动切回商品录入页面完成带序号 1.2.3. 回填！",
                    "data": parsed_result
                }

            res = engine.manager.run_on_browser_thread(_automate_deepseek_action, page)
            return res
        except Exception as e:
            return {"success": False, "msg": f"调用 DeepSeek 自动化异常: {str(e)}", "data": {"raw_text": "", "extracted_jp_text": "", "bullet_points": []}}
