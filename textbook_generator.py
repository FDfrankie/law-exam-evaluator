# -*- coding: utf-8 -*-
"""
code/textbook_generator.py
體系導引式法學教科書自學引擎 (Structured Syllabus-Driven Legal Textbook Engine)

核心特色：
1. 法學體系課表導引：讀取 data/curriculum_syllabus.json，循序漸進引導學習者深入法學殿堂。
2. 上下文自動聯動：自動結合 six_codes_engine（法定條文與立法意旨）及 judicial_authority.db（判例要旨與權威見解）。
3. 權威教科書質感撰寫：
   - 【本講學習導引】
   - 【第一節：基礎法理與規範機能】
   - 【第二節：構成要件逐層拆解】
   - 【第三節：實務與學說爭議深研（甲說、乙說、折衷說對決與判例字號）】
   - 【第四節：經典國考實戰演習（IRAC 完整開標擬答）】
"""

import os
import sys
import json
import sqlite3
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

# 終端編碼防護
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 專案路徑設定
CURRENT_FILE = Path(__file__).resolve()
CODE_DIR = CURRENT_FILE.parent
PROJECT_ROOT = CODE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"

try:
    from config import get_gemini_api_key, DEFAULT_GEMINI_MODEL, get_gemini_models_to_try
except Exception:
    def get_gemini_api_key():
        return os.environ.get("GEMINI_API_KEY", "")
    DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
    def get_gemini_models_to_try():
        return ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]

# 引入六法引擎
try:
    from six_codes_engine import (
        search_articles,
        get_article_legislative_details,
        format_legal_article_text,
        parse_article_query
    )
except Exception:
    def search_articles(*args, **kwargs): return []
    def get_article_legislative_details(*args, **kwargs): return {}
    def format_legal_article_text(t): return t or ""
    def parse_article_query(kw, known_laws=None): return ("", None, False, kw)


# ==============================================================================
# 1. 課表讀取與快取 API
# ==============================================================================
_CACHED_SYLLABUS: Optional[Dict[str, Any]] = None

def _load_syllabus_data() -> Dict[str, Any]:
    """延遲加載課表 JSON 資料庫，具備多重後備路徑機制"""
    global _CACHED_SYLLABUS
    if _CACHED_SYLLABUS is not None:
        return _CACHED_SYLLABUS

    candidates = [
        DATA_DIR / "curriculum_syllabus.json",
        CODE_DIR / "data" / "curriculum_syllabus.json",
        PROJECT_ROOT / "curriculum_syllabus.json",
        Path(r"G:\我的雲端硬碟\LawExamData\code\data\curriculum_syllabus.json")
    ]

    for p in candidates:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    _CACHED_SYLLABUS = json.load(f)
                    return _CACHED_SYLLABUS
            except Exception as e:
                print(f"[TextbookEngine] 讀取課表 {p} 失敗: {e}")

    _CACHED_SYLLABUS = {}
    return _CACHED_SYLLABUS


def get_available_subjects() -> List[str]:
    """回傳所有已收錄體系大綱的學習科目（例如：民法、刑法、智慧財產權法）"""
    data = _load_syllabus_data()
    return list(data.keys()) if data else ["民法", "刑法", "智慧財產權法"]


def get_subject_syllabus(subject: str) -> Dict[str, List[dict]]:
    """回傳指定科目的所有體系編章與講次清單"""
    data = _load_syllabus_data()
    if subject in data and isinstance(data[subject], dict):
        return data[subject]
    
    # 模糊比對
    for s_name, ch_map in data.items():
        if subject in s_name or s_name in subject:
            return ch_map
    return {}


def get_all_topics_for_subject(subject: str) -> List[dict]:
    """回傳某科目的所有專題講次扁平清單（方便統計學習進度）"""
    syll = get_subject_syllabus(subject)
    all_topics = []
    for ch_name, topics in syll.items():
        if isinstance(topics, list):
            for t in topics:
                t_copy = dict(t)
                t_copy["chapter"] = ch_name
                all_topics.append(t_copy)
    return all_topics


def get_topic_by_id(subject: str, topic_id: str) -> Optional[dict]:
    """根據 topic_id 搜尋專題講次"""
    for t in get_all_topics_for_subject(subject):
        if t.get("id") == topic_id:
            return t
    return None


# ==============================================================================
# 2. 上下文自動聯動：條文全文、立法意旨與權威判例高速檢索
# ==============================================================================
def _find_authority_db_path() -> Optional[Path]:
    """搜尋 judicial_authority.db 實體路徑"""
    candidates = [
        DATA_DIR / "judicial_authority.db",
        PROJECT_ROOT / "judicial_authority.db",
        CODE_DIR / "judicial_authority.db",
        Path(r"G:\我的雲端硬碟\LawExamData\judicial_authority.db")
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def fetch_topic_context(topic: dict, max_articles: int = 6, max_precedents: int = 5) -> Dict[str, Any]:
    """
    依據專題之 articles 清單，全自動高速撈取：
    1. 條文法定全文與規範內容（six_codes_engine / national_laws）
    2. 立法沿革與立法意旨（get_article_legislative_details）
    3. 命中該條號之最高法院經典判例要旨與重大裁判（judicial_authority.db）
    """
    raw_articles = topic.get("articles", [])
    articles_data = []
    precedents_data = []

    # 1. 檢索法條與立法意旨
    for art_str in raw_articles[:max_articles]:
        clean_art = art_str.strip()
        # 拆解法名與條號，如 "民法第184條" -> law="民法", no="184"
        detected_law, target_no, _, _ = parse_article_query(clean_art)
        if not detected_law:
            if "民法" in clean_art: detected_law = "民法"
            elif "刑法" in clean_art: detected_law = "刑法"
            elif "專利" in clean_art: detected_law = "專利法"
            elif "商標" in clean_art: detected_law = "商標法"
            elif "著作" in clean_art: detected_law = "著作權法"
            elif "土地法" in clean_art: detected_law = "土地法"
            elif "藥事法" in clean_art: detected_law = "藥事法"
        
        m_num = re.search(r'第?\s*(\d+(?:之\d+|-\d+)?)條?', clean_art)
        raw_num = m_num.group(1) if m_num else target_no or ""
        pure_num = re.sub(r'[^\d\-之]', '', str(raw_num)).replace("之", "-")

        matched_title = f"{detected_law} 第 {pure_num} 條" if (detected_law and pure_num) else clean_art
        matched_content = ""

        if pure_num:
            search_res = search_articles(f"第{pure_num}條", selected_law=detected_law)
            if search_res:
                matched_content = search_res[0].get("content", "")
                law_n = search_res[0].get('law_name') or detected_law
                art_n = str(search_res[0].get('article_no') or pure_num).strip()
                if not art_n.startswith("第"):
                    art_n = f"第 {art_n} 條"
                elif not art_n.endswith("條"):
                    art_n = f"{art_n} 條"
                matched_title = f"{law_n} {art_n}"
        
        # 撈取立法意旨
        leg_details = {}
        if detected_law and pure_num:
            try:
                leg_details = get_article_legislative_details(detected_law, pure_num)
            except Exception:
                pass

        leg_text = ""
        if leg_details:
            leg_text = leg_details.get("reason", "") or leg_details.get("history_text", "")

        articles_data.append({
            "query": clean_art,
            "title": matched_title,
            "law_name": detected_law,
            "article_no": pure_num,
            "content": matched_content,
            "legislative_reason": leg_text[:500] if leg_text else ""
        })

    # 2. 高速檢索 judicial_authority.db 命中判例（針對 precedents 4000+ 權威判例庫精準命中）
    auth_db_path = _find_authority_db_path()
    if auth_db_path:
        try:
            conn = sqlite3.connect(auth_db_path, timeout=3)
            cursor = conn.cursor()

            for art_item in articles_data:
                law_n = art_item.get("law_name", "")
                ano = art_item.get("article_no", "")
                if not ano:
                    continue

                # 組合檢索關鍵字：如 '%民法%184%' 或 '%184%'
                kw_pat = f"%{law_n}%{ano}%" if law_n else f"%{ano}%"

                # 查詢最高法院經典判例（速度極快，毫秒級回傳）
                try:
                    q_prec = """
                        SELECT precedent_id, holding, sys_type
                        FROM precedents
                        WHERE laws_cited LIKE ?
                        LIMIT 3
                    """
                    cursor.execute(q_prec, (kw_pat,))
                    for row in cursor.fetchall():
                        prec_id, holding, sys_type = row
                        if holding:
                            precedents_data.append({
                                "source": f"最高法院判例 ({sys_type or '判例'})",
                                "case_no": prec_id,
                                "title": prec_id,
                                "holding": holding[:350].strip()
                            })
                except Exception:
                    pass

                if len(precedents_data) >= max_precedents:
                    break

            conn.close()
        except Exception as e_db:
            print(f"[TextbookEngine] 資料庫查詢錯誤: {e_db}")

    return {
        "topic": topic,
        "articles": articles_data,
        "precedents": precedents_data[:max_precedents]
    }


# ==============================================================================
# 3. 專題教科書撰寫 Prompt 與長文架構
# ==============================================================================
def build_textbook_prompt(subject: str, chapter: str, topic: dict, context_data: dict) -> str:
    """
    建構權威法學教科書深度的 Prompt，貫徹四節標準學術架構
    """
    title = topic.get("title", "")
    core_concepts = topic.get("core_concepts", [])
    articles = context_data.get("articles", [])
    precedents = context_data.get("precedents", [])

    # 格式化條文與立法意旨提示
    law_contexts = []
    for a in articles:
        c_txt = a.get("content", "").strip()
        leg_txt = a.get("legislative_reason", "").strip()
        law_str = f"📜 【{a.get('title')}】\n條文內容：{c_txt if c_txt else '（本條規範意旨詳見下述）'}"
        if leg_txt:
            law_str += f"\n立法意旨/理由：{leg_txt}"
        law_contexts.append(law_str)
    laws_block = "\n\n".join(law_contexts) if law_contexts else "（由模型調用內建六法典藏完整展開）"

    # 格式化判例要旨
    prec_contexts = []
    for p in precedents:
        prec_str = f"🏛️ 【{p.get('source')}】{p.get('case_no')}《{p.get('title')}》\n核心要旨：{p.get('holding')[:250]}..."
        prec_contexts.append(prec_str)
    precs_block = "\n\n".join(prec_contexts) if prec_contexts else "（由模型調用最高法院最新大法庭裁定與經典判例完整融入）"

    concepts_str = "、".join(core_concepts)

    prompt = f"""你是一位享譽法學界的頂尖法學講座教授與權威法學教科書作者（文筆風格兼具王澤鑑老師的嚴謹體系請求權基礎思維、林山田老師的犯罪論精密階層、以及最高法院大法庭的最新實務洞察）。
請針對下列法學體系特定講次，為司律二試與司法官高普考考生撰寫一章具備**權威專題教科書深度、結構嚴謹且兼具實戰性**的深度專題教材。

============================================================
【研讀科目】：{subject}
【所屬體系單元】：{chapter}
【本講主題】：{title}
【涵蓋核心概念】：{concepts_str}
============================================================

【系統即時聯動檢索之法條與立法意旨】：
{laws_block}

【系統即時命中之權威判例與重大見解庫】：
{precs_block}

============================================================
【寫作規範與章節體例要求】：
請拋棄走馬看花式的簡要概述，字數需具備足夠份量（約 2,500 ~ 4,000 字之紮實專論），並嚴格按照以下標準教科書體例進行排版與論述：

# 《{title}》

## 🧭【本講學習導引】
- 點明本講專題在《{subject}》整體體系地圖中的關鍵樞紐地位。
- 說明前置基礎概念（承前）與後續延伸爭點（啟後），建立清晰的體系座標。
- 列出本講必備三大核心思維工具。

## 📜【第一節：基礎法理與規範機能】
- 立法目的與規範價值：深入探討本專題相關條文背後的法政策、保護法益或利益衡量核心。
- 若有立法沿革或外國法繼受背景（德、日或英美法理），請精準點出其制度演進脈絡。
- 規範意旨：法律為何在此創設此一制度？解決了社會生活中的何種交易風險或秩序衝突？

## ⚖️【第二節：構成要件逐層拆解與審查階層】
- 以嚴密的體系圖或條列式拆解所有客觀要件與主觀要件。
- 舉證責任分配：依客觀舉證責任法則（如規範說/修正規範說），精確標示各要件應由何造當事人負擔舉證責任。
- 法律效果：要件該當後產生之物權效力、債權請求權或刑事處罰邊界。

## 🏛️【第三節：實務與學說爭議深研（核心交鋒陣地）】
針對本講最關鍵的核心爭議點（至少列出 2~3 個司律必考經典爭點），務必嚴格對決：
1. **問題緣起與爭鳴核心**：以實例問題引出法條文字之模糊或漏洞。
2. **實務見解（甲說）**：詳細列舉最高法院判例、重要決議、大法庭裁定字號（例如：XX年台上字第XX號、108年度台上大字第XX號），詳述其判斷理由與心證。
3. **學說通說/有力說（乙說）**：引述國內權威學者（如王澤鑑、林山田、黃榮堅、謝在全、王敏銓等）之學理批判，點出實務見解之盲點。
4. **評析與自說（管見）**：提供司律二試閱卷委員最欣賞的折衷說或體系一貫性論證，教導考生如何在試卷上漂亮收尾。

## 🎯【第四節：經典國考實戰演習（IRAC 完整開標擬答）】
- 設計一道高度逼真、融合本講所有核心爭點之【司律二試全真綜合實例題】（含人名、金錢/行為事實背景）。
- 示範標準 IRAC（Issue 爭點 ➔ Rule 法條規範 ➔ Application 案例涵攝 ➔ Conclusion 結論）四段論法。
- 依正式國考答題規格完整開標（如：一、(一)、1.），展示高分上榜卷的邏輯穿透力與精確涵攝技巧。

============================================================
請以流暢、權威、清晰、高質感的 Markdown 格式輸出，重點字詞適當使用粗體標記，法條與判例字號請精確呈現！
"""
    return prompt


# ==============================================================================
# 4. 教科書生成核心執行器 (TextbookGenerator Class)
# ==============================================================================
class TextbookGenerator:
    """法學教科書自學引擎生成器"""

    def __init__(self, model_name: str = DEFAULT_GEMINI_MODEL):
        self.model_name = model_name
        self.api_key = get_gemini_api_key()

    def generate_chapter(
        self,
        subject: str,
        chapter: str,
        topic: dict,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        執行專題教材生成全流程：
        1. 自動搜集條文全文與權威判例上下文
        2. 組裝權威專題 Prompt
        3. 調用 Gemini 模型長篇生成
        """
        if not self.api_key:
            raise ValueError("未偵測到 Gemini API Key，請先於設定區或環境變數填入 API Key！")

        if progress_callback:
            progress_callback("正在聯動六法全書與司法權威大庫，撈取條文意旨與判例要旨...")

        context_data = fetch_topic_context(topic)

        if progress_callback:
            progress_callback("正在以頂尖法學講座風格構建深度專題教科書框架...")

        prompt = build_textbook_prompt(subject, chapter, topic, context_data)

        if progress_callback:
            progress_callback(f"法學大模型 ({self.model_name}) 正在撰寫權威專題教科書長篇章節（約 3,000 字）...")

        content_markdown = self._call_ai(prompt)

        return {
            "success": True,
            "subject": subject,
            "chapter": chapter,
            "topic": topic,
            "context": context_data,
            "markdown": content_markdown
        }

    def _call_ai(self, prompt: str) -> str:
        """調用 Gemini 生成長篇教科書內容（支援 google-genai 新 SDK 與 legacy fallback）"""
        # 1. 嘗試新版 google-genai
        try:
            from google import genai
            from google.genai import types as genai_types
            client = genai.Client(api_key=self.api_key)

            models_to_try = [self.model_name] + [m for m in get_gemini_models_to_try() if m != self.model_name]
            last_err = None

            for m in models_to_try:
                try:
                    cfg = genai_types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=8192
                    )
                    resp = client.models.generate_content(
                        model=m,
                        contents=prompt,
                        config=cfg
                    )
                    if resp and resp.text:
                        return resp.text
                except Exception as ex:
                    last_err = ex
                    continue

            if last_err:
                raise last_err
        except ImportError:
            pass

        # 2. 嘗試舊版 google.generativeai
        try:
            import google.generativeai as legacy_genai
            legacy_genai.configure(api_key=self.api_key)
            models_to_try = [self.model_name, "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
            last_err = None
            for m in models_to_try:
                try:
                    mod = legacy_genai.GenerativeModel(model_name=m)
                    resp = mod.generate_content(prompt)
                    if resp and resp.text:
                        return resp.text
                except Exception as ex:
                    last_err = ex
                    continue
            if last_err:
                raise last_err
        except Exception as e_leg:
            raise RuntimeError(f"AI 生成失敗: {e_leg}")

        raise RuntimeError("無法成功調用 AI 服務")
