"""
商品维护 API 路由
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request
from server.models.product_schemas import ProductCreateSchema, GenerateMatrixRequest
from server.services.product_service import ProductService
from server.dependencies import get_current_user_from_request

router = APIRouter(prefix="/api/products", tags=["商品维护"])


@router.post("/generate-matrix", summary="自动生成多变体笛卡尔积矩阵")
async def generate_matrix(req: GenerateMatrixRequest):
    """根据提交的颜色与尺寸选项，实时计算笛卡尔积变体组合矩阵"""
    matrix = ProductService.generate_variation_matrix(req)
    return {"code": 0, "msg": "生成成功", "data": matrix}


@router.get("/seq-numbers", summary="获取当前用户与品牌的自动编号 (Parent SKU / 型号 / 型号名称)")
async def get_seq_numbers(request: Request, brand: Optional[str] = Query(None)):
    """
    自动生成编号规则：
    1. Parent SKU = 登录用户名 + 用户创建的第几个品 (数字)
    2. 品番・型番 = 品牌
    3. モデル名 = 品牌 + 该品牌下的第几个品 (数字)
    """
    user = get_current_user_from_request(request)
    username = user.get("username", "admin") if user else "admin"
    seq_data = ProductService.get_next_sequence_numbers(username, brand or "")
    return {"code": 0, "msg": "获取成功", "data": seq_data}


@router.get("/filter-options", summary="获取商品列表筛选下拉可选项")
async def get_product_filter_options():
    """返回所有已录入商品的店铺、品牌与维护人列表，用于前端筛选器下拉菜单"""
    opts = ProductService.get_filter_options()
    return {"code": 0, "msg": "获取成功", "data": opts}


@router.post("/ai-prompt", summary="查看 AI 字段当前使用的 Ollama 提示词")
async def get_ai_prompt(request: Request):
    """根据模式与当前输入内容, 返回实际发送给本地 Ollama 的提示词 (供前端查看按钮展示)"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体必须为 JSON")

    mode = (body.get("mode") or "").strip()
    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()

    if mode == "title_translation":
        text = title
    elif mode == "identifier":
        text = content
    elif mode == "identifier_translation":
        text = content
    elif mode == "bullets":
        # 五点描述生成: 仅依赖标题
        text = title
    else:
        raise HTTPException(status_code=400, detail=f"未知的处理模式: {mode}")

    if not text:
        raise HTTPException(status_code=400, detail="请先填写对应字段内容，再查看提示词！")

    if mode == "bullets":
        prompt = build_bullets_prompt(title)
    else:
        prompt = build_ai_prompt(mode, title, content)
    return {"code": 0, "msg": "获取成功", "data": {"mode": mode, "prompt": prompt}}


def build_ai_prompt(mode: str, title: str, content: str) -> str:
    """构建各模式的 Ollama 提示词 (与实际调用保持一致)"""
    if mode == "title_translation":
        return f"将如下标题内容翻译成对应的中文标题：\n{title}"
    if mode == "identifier":
        # 该小模型易输出思考链, 采用 JSON 强制输出模式 (实测稳定)
        return (
            "从商品标题中提炼一个核心商品名词，去掉品牌、尺寸、数量、材质等修饰词。"
            "例：JoJoMaman 婴儿浴巾 带帽 纯棉 75x75cm→婴儿浴巾，犬用厕所垫 4个套装 42x34cm→犬用厕所垫。"
            '以JSON格式输出：{"noun": "提炼词"}\n\n'
            f"标题：{content}"
        )
    if mode == "identifier_translation":
        # 中文指令翻译效果差, 改用英文指令 (实测输出更稳定); 与提炼规则同步: 保留用途对象, 只去品牌/尺寸/数量/材质
        return (
            "Translate the following Chinese product name into an English product name. "
            "Keep the purpose/object prefix (e.g. baby/dog/pet), only remove brand, size, quantity and material words. "
            "Examples: 婴儿浴巾→Baby Bath Towel, 犬用厕所垫→Dog Toilet Pad. "
            "Output ONLY the English name (Title Case, separated by spaces), nothing else.\n\n"
            f"Product name: {content}"
        )
    return ""


@router.post("/extract-identifier", summary="AI 提取标题翻译/商品标识/标识英文翻译 (本地 Ollama)")
async def extract_identifier_ai(request: Request):
    """
    本地 Ollama AI 文本处理, 支持三种模式 (mode):
    1. title_translation: 将商品标题翻译成中文标题 (prompt: 将如下标题内容翻译成对应的中文标题：)
    2. identifier: 将标题翻译内容提炼成一个中文词表述
    3. identifier_translation: 将商品标识翻译成英文
    """
    import json as _json
    import re as _re
    import urllib.request
    import asyncio

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体必须为 JSON")

    mode = (body.get("mode") or "title_translation").strip()
    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()

    if mode == "title_translation":
        if not title:
            raise HTTPException(status_code=400, detail="请先填写产品标题！")
    elif mode == "identifier":
        if not content:
            raise HTTPException(status_code=400, detail="请先完成标题翻译，再提炼商品标识！")
    elif mode == "identifier_translation":
        if not content:
            raise HTTPException(status_code=400, detail="请先填写商品标识，再翻译成英文！")
    else:
        raise HTTPException(status_code=400, detail=f"未知的处理模式: {mode}")

    prompt = build_ai_prompt(mode, title, content)

    OLLAMA_BASE = "http://127.0.0.1:11434"

    # 本地模型优先取管理台配置 (默认 qwen2.5:1.5b-instruct-q4_K_M), 未安装时回退自动识别
    from server.database import get_setting as _get_setting
    configured_model = (_get_setting("ai_ollama_model", "") or "").strip()
    model = ""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=5) as resp:
            tags = _json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in tags.get("models", []) if m.get("name")]
            if configured_model:
                matched = [m for m in models if m.lower() == configured_model.lower() or m.split(":")[0].lower() == configured_model.lower()]
                model = matched[0] if matched else configured_model
            else:
                preferred = [m for m in models if "qwen2.5:1.5b" in m.lower()]
                model = (preferred or models)[0] if models else ""
    except Exception:
        model = configured_model  # Ollama 不可达时仍尝试用配置的模型名调用, 由后续请求报错
    if not model:
        raise HTTPException(status_code=503, detail="本地 Ollama 服务不可用或未安装任何模型，请先启动 Ollama！")

    payload = _json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        # 商品标识提炼用 JSON 强制输出, 避免小模型输出思考链
        **({"format": "json"} if mode == "identifier" else {}),
        "options": {"temperature": 0.1, "num_predict": 512}
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"}
        )

        def _call_ollama():
            with urllib.request.urlopen(req, timeout=90) as resp:
                return _json.loads(resp.read().decode("utf-8"))

        # 阻塞式 HTTP 调用放入线程池, 避免卡死 FastAPI 事件循环 (否则整个服务无法响应其他请求)
        result = await asyncio.to_thread(_call_ollama)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"调用本地 Ollama 失败: {str(e)}")

    raw = result.get("response", "") or ""
    # 思考型模型: 优先取 </think> 之后的内容, 再去除成对 <think> 标签
    if "</think>" in raw:
        raw = raw.split("</think>", 1)[1]
    raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.S)

    answer = ""
    # JSON 强制输出模式: 直接解析 noun 字段
    if mode == "identifier":
        try:
            parsed = _json.loads(raw)
            noun = str(parsed.get("noun") or "").strip()
            if noun:
                answer = noun
        except Exception:
            pass

    # 解析答案: 取最后一个非空行 (模型可能先解释后作答), 去除引号与装饰符
    if not answer:
        candidate_lines = [
            l.strip().strip('"“”\'「」『』').strip("-•* ").strip()
            for l in raw.splitlines() if l.strip()
        ]
        answer = candidate_lines[-1] if candidate_lines else ""
    if not answer:
        # 兜底: 提取末尾引号内的短语
        m = _re.findall(r'"([^"]{2,60})"', raw)
        answer = m[-1].strip() if m else ""
    if len(answer) > 200:
        answer = answer[:200].rstrip()

    if not answer:
        raise HTTPException(status_code=500, detail="AI 未返回有效结果，请手动填写")
    # 商品标识英文翻译: 仅保留英文字母并 Title Case 连写 (如 Dog-Shaped Toilet -> DogShapedToilet)
    if mode == "identifier_translation":
        answer = _re.sub(r"[^A-Za-z]", "", answer.title())

    return {"code": 0, "msg": "处理成功", "data": {"result": answer, "mode": mode, "model": model}}


def build_bullets_prompt(title: str) -> str:
    """构建五点描述生成提示词 (与录入页 DeepSeek 助手 buildJapaneseDescAiPrompt 保持一致)"""
    return (
        "你是一位资深亚马逊日本的卖家文案专家，擅长撰写详实、有说服力的日文商品五点描述。"
        "请基于这个品的日文标题，生成标准的5条日语五点描述，要求如下：\n"
        "1. 【条数硬性约束】日文版必须且只能输出 5 条（编号 1. 2. 3. 4. 5.），中文翻译同样必须且只能输出 5 条，与日文版一一对应，严禁少于 5 条、多于 5 条或输出任何额外说明文字；\n"
        "2. 每条围绕一个不同的卖点，从材质、设计、功能、清洁保养、使用场景等角度分别展开，内容不得重复；\n"
        "3. 每条以「【卖点】」开头（如【素材】【設計】【機能】【お手入れ】【シーン】），后接一段完整、详实的日文描述；\n"
        "4. 【内容质量硬性约束】每条必须是 50-100 字的完整日文句子（含标点），要包含：具体的功能/材质说明 + 带给买家的实际好处。"
        "严禁只输出几个词或短语！例如「【素材】人工芝」是不合格的，合格示例："
        "「【素材】丈夫で通気性の良い人工芝を採用しており、ペットの足元にやさしく、匂いが残りにくく、長期間清潔にご使用いただけます。」；\n"
        "5. 除以下指定格式外，不要输出任何其他内容（包括开场白、结尾、解释）。\n"
        "输出格式（严格遵守，日文版 5 条、中文翻译 5 条，共 10 行）：\n"
        "一、日文版\n"
        "&&&&&&&&&&&&&&&&&&&\n"
        "1. xxx\n2. xxx\n3. xxx\n4. xxx\n5. xxx\n"
        "&&&&&&&&&&&&&&&&&&&\n"
        "二、中文翻译\n"
        "1. xxx\n2. xxx\n3. xxx\n4. xxx\n5. xxx\n"
        f"具体标题如下：{title}"
    )


@router.post("/generate-bullets", summary="AI 生成日文五点描述 (管理台配置的大模型)")
async def generate_bullets_ai(request: Request):
    """输入标题后自动调用大模型生成日文五点描述与中文翻译, 提示词与 DeepSeek 助手一致"""
    import json as _json
    import urllib.request

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体必须为 JSON")

    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="请先填写产品标题！")

    # 读取管理台 AI 配置 (与管理台默认值保持一致)
    from server.database import get_setting
    source = (get_setting("ai_bullets_source", "") or "").strip().lower()
    if source not in ("local", "public"):
        source = "public"
    ollama_model = (get_setting("ai_ollama_model", "") or "").strip() or "qwen2.5:1.5b-instruct-q4_K_M"
    base_url = ((get_setting("ai_api_base_url", "") or "").strip() or "https://api.deepseek.com").rstrip("/")
    model = (get_setting("ai_model_name", "") or "").strip() or "deepseek-v4-flash"
    api_key = (get_setting("ai_api_key", "") or "").strip() or "sk-44d5b47efaa64e3a967efc0c8fc05ce2"
    if source == "public" and not api_key:
        raise HTTPException(status_code=503, detail="未配置大模型 API Key，请前往管理台配置！")

    # 提示词与录入页 DeepSeek 助手 (buildJapaneseDescAiPrompt) 保持一致
    prompt = build_bullets_prompt(title)

    import asyncio as _asyncio
    import time as _time

    def _call_llm():
        """阻塞式调用大模型 (在独立线程中执行, 避免卡死事件循环); 返回 (回复文本, 模型名, token用量dict)"""
        if source == "local":
            ollama_payload = _json.dumps({
                "model": ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 1024}
            }).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/generate",
                data=ollama_payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                result = _json.loads(resp.read().decode("utf-8"))
            # Ollama token 统计字段
            usage = {
                "prompt_tokens": int(result.get("prompt_eval_count") or 0),
                "completion_tokens": int(result.get("eval_count") or 0)
            }
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
            return result.get("response", "") or "", ollama_model, usage
        # 公共大模型 API (OpenAI 兼容); deepseek-v4 系列默认开启思考模式且思考 token 计入 completion_tokens,
        # 五点描述为固定模板任务无需深度推理, 显式关闭 thinking 以大幅降低 token 消耗
        payload = _json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "stream": False,
            "thinking": {"type": "disabled"}
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
        content = (result.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        usage = result.get("usage") or {}
        return content, model, {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0)
        }

    started_at = _time.monotonic()
    status, error_detail, usage = "success", "", {}
    try:
        raw, model_used, usage = await _asyncio.to_thread(_call_llm)
    except Exception as e:
        status, error_detail = "error", str(e)[:2000]
        raw, model_used = "", model
    duration_ms = int((_time.monotonic() - started_at) * 1000)

    # 记录本次大模型调用日志 (成功与失败均记录, 用于 token 统计与排查)
    try:
        from server.database import get_db_connection
        user = get_current_user_from_request(request)
        username = user.get("username", "") if user else ""
        log_conn = get_db_connection()
        try:
            log_conn.execute("""
                INSERT INTO llm_call_logs (scene, source, model, title, prompt, response, status, error_detail,
                                           prompt_tokens, completion_tokens, total_tokens, duration_ms, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "bullets", source, model_used, title, prompt, raw[:20000] if raw else "",
                status, error_detail,
                usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), usage.get("total_tokens", 0),
                duration_ms, username
            ))
            log_conn.commit()
        finally:
            log_conn.close()
    except Exception as log_err:
        print(f"[LLM日志] 写入失败(不影响主流程): {log_err}")

    if status == "error":
        raise HTTPException(status_code=502, detail=f"调用大模型失败: {error_detail}")

    if not raw.strip():
        raise HTTPException(status_code=500, detail="大模型未返回有效内容，请重试或手动生成")

    return {"code": 0, "msg": "生成成功", "data": {"raw": raw, "model": model_used, "source": source}}


@router.post("", summary="保存/创建商品与变体信息")
async def create_product(data: ProductCreateSchema, request: Request):
    """保存商品完整信息至本地数据库，维护人取当前登录账号"""
    user = get_current_user_from_request(request)
    username = user.get("username", "admin") if user else "admin"
    product = ProductService.create_product(data, created_by=username)
    return {"code": 0, "msg": "商品录入成功", "data": product}


@router.put("/{product_id}", summary="更新修改商品与变体信息")
async def update_product(product_id: int, data: ProductCreateSchema):
    """更新修改已有商品及变体完整信息"""
    product = ProductService.update_product(product_id, data)
    if not product:
        raise HTTPException(status_code=404, detail=f"ID 为 {product_id} 的商品不存在")
    return {"code": 0, "msg": "商品更新成功", "data": product}


@router.get("/by-parent-sku/{parent_sku}", summary="按 Parent SKU 获取商品完整数据（用于录入页面导入回填）")
async def get_product_by_parent_sku(parent_sku: str):
    """按 Parent SKU 查询商品父节点及全部变体，用于录入工作台导入已保存商品数据"""
    from server.database import get_db_connection
    import json as _json
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT * FROM product_items WHERE parent_sku = ? AND is_parent = 1 LIMIT 1",
            (parent_sku,)
        )
        p_row = cursor.fetchone()
        if not p_row:
            raise HTTPException(status_code=404, detail=f"Parent SKU '{parent_sku}' 不存在")
        product = dict(p_row)
        # 反序列化 JSON 字段
        for json_field, alias in [
            ("extra_images_json", "extra_images"),
            ("color_options_json", "color_options"),
            ("size_options_json", "size_options"),
            ("variant_dimension_images_json", "variant_dimension_images"),
            ("bullet_points_json", "bullet_points"),
            ("chinese_translations_json", "chinese_translations"),
        ]:
            try:
                product[alias] = _json.loads(product.get(json_field) or ("[]" if alias != "variant_dimension_images" else "{}"))
            except Exception:
                product[alias] = [] if alias != "variant_dimension_images" else {}

        # 查询子变体
        cursor.execute(
            "SELECT * FROM product_items WHERE parent_sku = ? AND is_parent = 0 ORDER BY id ASC",
            (parent_sku,)
        )
        v_rows = cursor.fetchall()
        product["variations"] = [dict(v) for v in v_rows]
        product["variation_count"] = len(product["variations"])
        return {"code": 0, "msg": "获取成功", "data": product}
    finally:
        conn.close()


@router.get("/list-parent-skus", summary="获取所有父级商品 Parent SKU 列表（用于录入页面导入选择）")
async def list_parent_skus():
    """返回所有 is_parent=1 的商品简要信息列表，供录入工作台导入下拉框使用"""
    from server.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, parent_sku, sku, title, brand, store_account, status, created_by, main_image
            FROM product_items
            WHERE is_parent = 1
            ORDER BY id DESC
            LIMIT 200
        """)
        rows = cursor.fetchall()
        return {"code": 0, "msg": "获取成功", "data": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/{product_id}", summary="获取商品详情")
async def get_product_detail(product_id: int):
    """获取指定商品的完整结构化数据"""
    product = ProductService.get_product_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    return {"code": 0, "msg": "获取成功", "data": product}


@router.get("", summary="获取商品列表 (支持多条件组合检索与模糊查询)")
async def list_products(
    keyword: Optional[str] = Query(None, description="搜索标题/Parent SKU/型号/关键词"),
    store_account: Optional[str] = Query(None, description="店铺账号筛选"),
    brand: Optional[str] = Query(None, description="品牌筛选"),
    created_by: Optional[str] = Query(None, description="维护人筛选"),
    sale_type: Optional[str] = Query(None, description="售卖形式筛选 (variation / single)"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """获取录入的商品列表与变体总数看板"""
    products = ProductService.list_products(
        limit=limit,
        offset=offset,
        keyword=keyword,
        store_account=store_account,
        brand=brand,
        created_by=created_by,
        sale_type=sale_type
    )
    return {"code": 0, "msg": "获取成功", "data": products}
