"""
統一 Gemini LLM 用戶端與模型後備調度引擎 (Core LLM Client)
提供：
1. 現代化 google-genai Client 統一封裝與重用。
2. 智慧模型階梯自動後備降級 (404/Quota 容錯)。
3. 強健的 Markdown JSON 提取與語法修復 (repair_and_parse_json)。
4. 多模態 (圖片、PDF、音訊) 統一呼叫介面。
"""

import os
import re
import json
from typing import Any, Dict, List, Optional, Union

from config import (
    get_gemini_api_key,
    DEFAULT_GEMINI_MODEL,
    GEMINI_FALLBACK_MODELS,
    get_gemini_models_to_try
)

_CLIENT_INSTANCE = None

def get_genai_client(api_key: Optional[str] = None):
    """取得或初始化 google.genai Client 實例"""
    global _CLIENT_INSTANCE
    key = api_key or get_gemini_api_key()
    if not key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=key)
    except Exception as e:
        print(f"[LLM CLIENT ERROR] 初始化 google-genai Client 失敗: {e}")
        return None

def is_gemini_available(api_key: Optional[str] = None) -> bool:
    """檢查 Gemini API Key 是否已配置"""
    key = api_key or get_gemini_api_key()
    return bool(key and len(key.strip()) > 10)

def repair_and_parse_json(raw_text: str) -> Optional[Any]:
    """強健修復並解析包含 Markdown 或格式缺陷之 JSON 字串"""
    if not raw_text:
        return None
    text = raw_text.strip()
    
    # 移除包裹的 ```json ... ``` 或 ``` ... ```
    if "```" in text:
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text, re.IGNORECASE)
        if match:
            text = match.group(1).strip()

    # 直接嘗試解析
    try:
        return json.loads(text)
    except Exception:
        pass

    # 嘗試提取第一個成對的 { ... } 或 [ ... ]
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    first_bracket = text.find('[')
    last_bracket = text.rfind(']')

    # 判斷是物件還是陣列
    if first_brace != -1 and last_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
        candidate = text[first_brace:last_brace + 1]
    elif first_bracket != -1 and last_bracket != -1:
        candidate = text[first_bracket:last_bracket + 1]
    else:
        candidate = text

    try:
        return json.loads(candidate)
    except Exception:
        pass

    # 移除逗號結尾等常見語法錯誤
    sanitized = re.sub(r',\s*([\}\]])', r'\1', candidate)
    try:
        return json.loads(sanitized)
    except Exception:
        return None

def call_gemini_text(
    prompt: str,
    primary_model: Optional[str] = None,
    system_instruction: Optional[str] = None,
    temperature: float = 0.2,
    api_key: Optional[str] = None,
    extra_contents: Optional[List[Any]] = None
) -> str:
    """
    呼叫 Gemini 生成文字，依優先順序自動嘗試模型階梯，確保無 404 中斷。
    """
    client = get_genai_client(api_key)
    if not client:
        raise ValueError("尚未設定 GEMINI_API_KEY，請於側邊欄或環境變數中設定。")

    models_to_try = get_gemini_models_to_try(primary_model)
    contents = [prompt]
    if extra_contents:
        contents = extra_contents + contents

    last_error = None
    for model_name in models_to_try:
        try:
            config_params: Dict[str, Any] = {"temperature": temperature}
            if system_instruction:
                config_params["system_instruction"] = system_instruction
            
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config_params
            )
            if response and hasattr(response, "text") and response.text:
                return response.text.strip()
        except Exception as e:
            last_error = e
            # 若為配額或模型不存在，自動嘗試下一順位模型
            continue

    raise RuntimeError(f"所有 Gemini 模型呼叫均失敗，最後錯誤: {last_error}")

def call_gemini_json(
    prompt: str,
    primary_model: Optional[str] = None,
    system_instruction: Optional[str] = None,
    temperature: float = 0.2,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """呼叫 Gemini 並自動解析修復為結構化 JSON 字典/清單"""
    json_prompt = f"{prompt}\n\n【特別要求】：請嚴格輸出合法的 JSON 格式，不要包含任何開頭問候語或結尾客套話。"
    text_out = call_gemini_text(
        prompt=json_prompt,
        primary_model=primary_model,
        system_instruction=system_instruction,
        temperature=temperature,
        api_key=api_key
    )
    parsed = repair_and_parse_json(text_out)
    if parsed is not None:
        return parsed
    raise ValueError(f"無法將模型回傳文字解析為 JSON。原始文字前 300 字:\n{text_out[:300]}")
