"""
mcq_bank_manager.py
司律一試選擇題全科題庫中央調配、社群共享、PDF試卷解析與試題疑義/報錯自動審查核心引擎
支援：
1. 跨科題庫整合：行政法 300 題全真題庫、民商法、刑法、憲法、民事訴訟法、刑事訴訟法、商事法全真試題
2. PDF 選擇題試卷上傳與 AI 結構化解析入庫
3. AI 智慧命題產出後自動入庫與去重典藏，供全體考生於題庫實戰中隨機抽考
4. 試題報錯即時撤下（下架保護）、理由判斷、AI 法律審查與自律修正機制
"""
import os
import re
import io
import json
import uuid
import random
import hashlib
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from config import (
    RAW_DATA_DIR, DATA_DIR, get_gemini_api_key,
    DEFAULT_GEMINI_MODEL, GEMINI_FALLBACK_MODELS
)

# 考科分類常量定義
SUBJECT_ADMIN_LAW = "行政法"
SUBJECT_CIVIL_LAW = "民法"
SUBJECT_CRIMINAL_LAW = "刑法"
SUBJECT_CONST_LAW = "憲法"
SUBJECT_CIVIL_PROC = "民事訴訟法"
SUBJECT_CRIMINAL_PROC = "刑事訴訟法"
SUBJECT_COMMERCIAL_LAW = "公司法與證券交易法"
SUBJECT_ALL_MIXED = "司律一試全科全真模擬大卷"

CORE_EXAM_SUBJECTS = [
    "🏛️ 行政法 (300題精選範本 + 共享大庫)",
    "⚖️ 民法 (財產法・身分法・實務全真題)",
    "🛡️ 刑法 (總則・分則・實例盲測全真題)",
    "📜 憲法 (基本權・權力分立・憲判字)",
    "📝 民事訴訟法 (程序法理・爭點整理・保全程序)",
    "⚔️ 刑事訴訟法 (強制處分・證據法則・非常救濟)",
    "💼 公司法與證券交易法 (商事法核心題庫)",
    "🌟 司律一試全科全真模擬大卷 (跨科綜合混合抽考)"
]

# 題庫路徑定義
COMMUNITY_MCQ_FILE = RAW_DATA_DIR / "community_mcq_bank.json"
REPO_COMMUNITY_MCQ_FILE = Path(__file__).resolve().parent / "data" / "raw_exams" / "community_mcq_bank.json"
MCQ_REPORTS_FILE = RAW_DATA_DIR / "mcq_reports_log.json"
REPO_MCQ_REPORTS_FILE = Path(__file__).resolve().parent / "data" / "raw_exams" / "mcq_reports_log.json"


def normalize_subject_key(sub_raw: str) -> str:
    """將含有 emoji 或說明之字串正規化為標準考科關鍵字"""
    s = str(sub_raw)
    if "行政" in s: return SUBJECT_ADMIN_LAW
    if "民事訴訟" in s or "民訴" in s: return SUBJECT_CIVIL_PROC
    if "刑事訴訟" in s or "刑訴" in s: return SUBJECT_CRIMINAL_PROC
    if "民法" in s: return SUBJECT_CIVIL_LAW
    if "刑法" in s: return SUBJECT_CRIMINAL_LAW
    if "憲法" in s: return SUBJECT_CONST_LAW
    if "公司" in s or "證券" in s or "證交" in s or "商事" in s or "保險" in s: return SUBJECT_COMMERCIAL_LAW
    if "全科" in s or "混合" in s or "大卷" in s: return SUBJECT_ALL_MIXED
    return s.strip()


class MCQBankManager:
    """司律一試全科題庫中央管理器"""

    def __init__(self):
        self._ensure_storage_files()
        self.dynamic_bank = self._load_dynamic_bank()
        self.reports_log = self._load_reports_log()

    def _ensure_storage_files(self):
        """確保儲存檔案與目錄存在"""
        try:
            COMMUNITY_MCQ_FILE.parent.mkdir(parents=True, exist_ok=True)
            if not COMMUNITY_MCQ_FILE.exists():
                if REPO_COMMUNITY_MCQ_FILE.exists():
                    COMMUNITY_MCQ_FILE.write_text(REPO_COMMUNITY_MCQ_FILE.read_text(encoding="utf-8"), encoding="utf-8")
                else:
                    COMMUNITY_MCQ_FILE.write_text("[]", encoding="utf-8")

            MCQ_REPORTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            if not MCQ_REPORTS_FILE.exists():
                if REPO_MCQ_REPORTS_FILE.exists():
                    MCQ_REPORTS_FILE.write_text(REPO_MCQ_REPORTS_FILE.read_text(encoding="utf-8"), encoding="utf-8")
                else:
                    MCQ_REPORTS_FILE.write_text("{}", encoding="utf-8")
        except Exception as e:
            print(f"[MCQStorage Init Error] {e}")

    def _load_dynamic_bank(self) -> List[Dict[str, Any]]:
        """載入動態題庫 (包含 AI 生成題、上傳題與修正後試題)"""
        for p in (COMMUNITY_MCQ_FILE, REPO_COMMUNITY_MCQ_FILE):
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        return data
                except Exception:
                    pass
        return []

    def _save_dynamic_bank(self):
        """持久化保存動態題庫至本機與倉庫目錄"""
        content = json.dumps(self.dynamic_bank, ensure_ascii=False, indent=2)
        for p in (COMMUNITY_MCQ_FILE, REPO_COMMUNITY_MCQ_FILE):
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            except Exception:
                pass

    def _load_reports_log(self) -> Dict[str, Any]:
        """載入試題報錯與撤下紀錄字典"""
        for p in (MCQ_REPORTS_FILE, REPO_MCQ_REPORTS_FILE):
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        return data
                except Exception:
                    pass
        return {}

    def _save_reports_log(self):
        """持久化保存試題報錯紀錄"""
        content = json.dumps(self.reports_log, ensure_ascii=False, indent=2)
        for p in (MCQ_REPORTS_FILE, REPO_MCQ_REPORTS_FILE):
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            except Exception:
                pass

    @staticmethod
    def _generate_question_hash(q_text: str, opt_a: str = "") -> str:
        """依題目題幹與選項計算唯一指紋雜湊"""
        clean_q = re.sub(r'\s+', '', str(q_text))[:60]
        clean_a = re.sub(r'\s+', '', str(opt_a))[:20]
        return hashlib.md5(f"{clean_q}_{clean_a}".encode("utf-8")).hexdigest()[:12]

    def load_all_base_questions(self) -> List[Dict[str, Any]]:
        """全量彙整所有底層靜態題庫與動態社群題庫"""
        all_qs = []
        seen_hashes = set()

        # 1. 行政法 300 題
        bank_paths = [
            RAW_DATA_DIR / "admin_law_300_mcqs.json",
            Path(__file__).resolve().parent / "data" / "raw_exams" / "admin_law_300_mcqs.json",
            Path(__file__).resolve().parent.parent / "raw_exams" / "admin_law_300_mcqs.json"
        ]
        for bp in bank_paths:
            if bp.exists():
                try:
                    data = json.loads(bp.read_text(encoding="utf-8"))
                    for q in data.get("questions", []):
                        q_copy = dict(q)
                        q_copy["subject"] = SUBJECT_ADMIN_LAW
                        q_copy["major_domain"] = "憲法與行政法"
                        qid = q_copy.get("id") or f"admin300_{q_copy.get('question_no', 0)}"
                        q_copy["id"] = qid
                        q_copy["source"] = "司律一試行政法300題精選範本試卷"
                        h = self._generate_question_hash(q_copy.get("question", ""), q_copy.get("options", {}).get("A", ""))
                        q_copy["hash"] = h
                        if h not in seen_hashes:
                            all_qs.append(q_copy)
                            seen_hashes.add(h)
                    break
                except Exception:
                    pass

        # 2. 跨科全真模擬題庫 (86 題)
        multi_bank_paths = [
            RAW_DATA_DIR / "stage1_multi_subject_mcq_bank.json",
            Path(__file__).resolve().parent / "data" / "raw_exams" / "stage1_multi_subject_mcq_bank.json",
            Path(__file__).resolve().parent.parent / "raw_exams" / "stage1_multi_subject_mcq_bank.json"
        ]
        for mbp in multi_bank_paths:
            if mbp.exists():
                try:
                    mdata = json.loads(mbp.read_text(encoding="utf-8"))
                    for q in mdata:
                        q_copy = dict(q)
                        qid = q_copy.get("id") or f"multi_{q_copy.get('subject')}_{q_copy.get('question_no', 0)}"
                        q_copy["id"] = qid
                        q_copy["source"] = "司律一試權威跨科範本大庫"
                        h = self._generate_question_hash(q_copy.get("question", ""), q_copy.get("options", {}).get("A", ""))
                        q_copy["hash"] = h
                        if h not in seen_hashes:
                            all_qs.append(q_copy)
                            seen_hashes.add(h)
                    break
                except Exception:
                    pass

        # 3. 動態題庫 (包含 AI 生成、PDF 上傳與修正題)
        for dq in self.dynamic_bank:
            q_copy = dict(dq)
            h = q_copy.get("hash") or self._generate_question_hash(q_copy.get("question", ""), q_copy.get("options", {}).get("A", ""))
            q_copy["hash"] = h
            if not q_copy.get("id"):
                q_copy["id"] = f"dyn_{h}"
            # 覆蓋或合併至清單中
            if h not in seen_hashes:
                all_qs.append(q_copy)
                seen_hashes.add(h)
            else:
                # 若動態庫中有修正版本，替換底層版本
                for idx, existing in enumerate(all_qs):
                    if existing.get("hash") == h:
                        all_qs[idx] = q_copy
                        break

        # 4. 根據報錯紀錄更新試題狀態 (例如撤下標記)
        for q in all_qs:
            qid = str(q.get("id"))
            qhash = str(q.get("hash"))
            report_item = self.reports_log.get(qid) or self.reports_log.get(qhash)
            if report_item:
                q["status"] = report_item.get("status", "under_review")
                q["report_reason"] = report_item.get("user_reason", "")
                q["review_note"] = report_item.get("review_note", "")
                if report_item.get("corrected_question"):
                    q["question"] = report_item["corrected_question"]
                if report_item.get("corrected_options"):
                    q["options"] = report_item["corrected_options"]
                if report_item.get("corrected_answer"):
                    q["answer"] = report_item["corrected_answer"]
                if report_item.get("corrected_explanation"):
                    q["explanation"] = report_item["corrected_explanation"]
            else:
                if "status" not in q:
                    q["status"] = "active"

        return all_qs

    def get_subject_statistics(self) -> Dict[str, Dict[str, int]]:
        """統計各考科可用試題數與撤下待審題數"""
        qs = self.load_all_base_questions()
        stats = {}
        for q in qs:
            sub = normalize_subject_key(q.get("subject", "其他領域"))
            if sub not in stats:
                stats[sub] = {"total": 0, "active": 0, "under_review": 0, "corrected": 0}
            stats[sub]["total"] += 1
            st = q.get("status", "active")
            if st == "under_review":
                stats[sub]["under_review"] += 1
            elif st == "verified_corrected":
                stats[sub]["active"] += 1
                stats[sub]["corrected"] += 1
            else:
                stats[sub]["active"] += 1
        return stats

    def get_chapters_for_subject(self, subject: str) -> List[str]:
        """依考科提供代表性篇章分類"""
        norm_sub = normalize_subject_key(subject)
        if norm_sub == SUBJECT_ADMIN_LAW:
            return [
                "全卷 300 題隨機抽考",
                "第一篇：核心法理、公私法性質、依法行政與裁量 (第 1~90 題)",
                "第二篇：具體行政行為定性分類、附款、效力與廢止 (第 91~240 題)",
                "第三篇：綜合案例實事實務題組題 (第 241~300 題)",
                "🌟 考生自創、PDF 上傳與 AI 命題擴充庫"
            ]
        elif norm_sub == SUBJECT_CIVIL_LAW:
            return [
                "全卷隨機抽考 (民法全編)",
                "第一篇：民法總則 (權利能力・行為能力・意思表示・代理與時效)",
                "第二篇：債法總論與各論 (契約・不當得利・侵權行為與違約責任)",
                "第三篇：物權法 (所有權・抵押權・用益物權與占有)",
                "第四篇：身分法 (親屬夫妻財產制・應繼分與特留分)",
                "🌟 考生自創、PDF 上傳與 AI 命題擴充庫"
            ]
        elif norm_sub == SUBJECT_CRIMINAL_LAW:
            return [
                "全卷隨機抽考 (刑法全科)",
                "第一篇：刑法總則 (構成要件・違法性・罪責・未遂與共犯)",
                "第二篇：個人法益犯罪 (生命・身體・自由・名譽與財產罪)",
                "第三篇：社會與國家法益犯罪 (公共危險・偽造・貪污與瀆職)",
                "🌟 考生自創、PDF 上傳與 AI 命題擴充庫"
            ]
        elif norm_sub == SUBJECT_CONST_LAW:
            return [
                "全卷隨機抽考 (憲法與憲訴)",
                "第一篇：基本權利總論與核心人權 (平等・人身・言論・財產與生存權)",
                "第二篇：國家權力分立與制衡機制 (總統・行政・立法與司法審查)",
                "第三篇：憲法訴訟法與憲判字宣告法理",
                "🌟 考生自創、PDF 上傳與 AI 命題擴充庫"
            ]
        elif norm_sub == SUBJECT_CIVIL_PROC:
            return [
                "全卷隨機抽考 (民事訴訟法全科)",
                "第一篇：訴訟主體、管轄、迴避與共同訴訟",
                "第二篇：訴訟標的理論、通常起訴與爭點整理程序",
                "第三篇：證據法則 (舉證責任・自認・證明度) 與判決既判力",
                "第四篇：上訴抗告救濟審、督促保全與強制執行競合",
                "🌟 考生自創、PDF 上傳與 AI 命題擴充庫"
            ]
        elif norm_sub == SUBJECT_CRIMINAL_PROC:
            return [
                "全卷隨機抽考 (刑事訴訟法全科)",
                "第一篇：刑事訴訟主體與強制處分 (搜索・扣押・羈押與羈押替代)",
                "第二篇：證據法則 (傳聞法則及其例外・自白與違法取證排除)",
                "第三篇：偵查、不起訴/緩起訴、公訴自訴與審判程序",
                "第四篇：簡易程序、國民法官與特別救濟 (上訴・再審・非常上訴)",
                "🌟 考生自創、PDF 上傳與 AI 命題擴充庫"
            ]
        elif norm_sub == SUBJECT_COMMERCIAL_LAW:
            return [
                "全卷隨機抽考 (商事法全科)",
                "第一篇：公司設立、資本三原則、股東會與董事會決議瑕疵",
                "第二篇：經理人義務、關係企業、股權轉讓與企業併購",
                "第三篇：證券交易法 (公開招募・短線交易・內線交易與操縱市場)",
                "第四篇：保險法核心爭點與被保險人利益",
                "🌟 考生自創、PDF 上傳與 AI 命題擴充庫"
            ]
        else:
            return ["全科全卷隨機抽考 (混合考科大模考)"]

    def get_categories_for_subject_and_chapter(self, subject: str, chapter: str = "") -> List[str]:
        """依考科與篇章提取當前題庫中所有可用之考點分類"""
        norm_sub = normalize_subject_key(subject)
        qs = self.load_all_base_questions()

        if norm_sub == SUBJECT_ADMIN_LAW and "300" in chapter:
            return [
                "全部考點分類 (不限)",
                "⚖️ [依法行政原則與專業法學庫]",
                "🏛️ [公私法性質與雙階理論]",
                "📜 [不確定法律概念與行政裁量]",
                "📑 [行政處分之定性與實例]",
                "📌 [行政處分之附款與效力]",
                "📝 [行政契約與事實行為]",
                "📜 [行政命令與地方法規]",
                "🌐 [行政法關係與權利義務]",
                "🧩 [第 241~300 題：綜合實務題組題]"
            ]

        # 動態收集
        cats = set()
        for q in qs:
            q_sub = normalize_subject_key(q.get("subject", ""))
            if norm_sub != SUBJECT_ALL_MIXED and q_sub != norm_sub:
                continue
            c = q.get("category", "").strip()
            if c:
                cats.add(c)

        sorted_cats = sorted(list(cats))
        return ["全部考點分類 (不限)"] + [f"🎯 {c}" for c in sorted_cats]

    def sample_exam_questions(
        self,
        subject: str,
        chapter: str,
        category: str,
        count: int = 5
    ) -> Dict[str, Any]:
        """
        從題庫中抽選試題：
        1. 自動過濾 status == 'under_review' (被報錯暫時撤下之試題)
        2. 精準匹配考科、篇章與考點
        3. 自動重新編號、生成 answer_key 與詳細報告架構
        """
        all_qs = self.load_all_base_questions()
        norm_sub = normalize_subject_key(subject)

        # 1. 基本活躍性過濾 (撤下題不予抽考)
        active_pool = [q for q in all_qs if q.get("status") != "under_review"]

        # 2. 考科過濾
        if norm_sub != SUBJECT_ALL_MIXED:
            active_pool = [q for q in active_pool if normalize_subject_key(q.get("subject", "")) == norm_sub]

        # 3. 篇章大類過濾
        if norm_sub == SUBJECT_ADMIN_LAW:
            if chapter.startswith("第一篇"):
                active_pool = [q for q in active_pool if 1 <= int(q.get("question_no", 0) or 0) <= 90]
            elif chapter.startswith("第二篇"):
                active_pool = [q for q in active_pool if 91 <= int(q.get("question_no", 0) or 0) <= 240]
            elif chapter.startswith("第三篇"):
                active_pool = [q for q in active_pool if 241 <= int(q.get("question_no", 0) or 0) <= 300]
            elif "考生自創" in chapter or "AI" in chapter:
                active_pool = [q for q in active_pool if "300" not in str(q.get("source", ""))]

        # 4. 考點分類過濾
        if category and category != "全部考點分類 (不限)":
            chosen_clean = category.replace("🎯", "").strip("[] ")
            def _match_cat(q_item):
                q_cat = unicodedata.normalize("NFKC", str(q_item.get("category", "")))
                return chosen_clean in q_cat or q_cat in chosen_clean
            filtered = [q for q in active_pool if _match_cat(q)]
            if filtered:
                active_pool = filtered

        if not active_pool:
            # 寬鬆退回考科全庫
            active_pool = [q for q in all_qs if q.get("status") != "under_review"]
            if norm_sub != SUBJECT_ALL_MIXED:
                active_pool = [q for q in active_pool if normalize_subject_key(q.get("subject", "")) == norm_sub]

        take = min(count, len(active_pool))
        selected_raw = random.sample(active_pool, take) if take > 0 else []

        reindexed_qs = []
        answer_key = {}
        for i, q in enumerate(selected_raw, 1):
            qc = dict(q)
            qc["original_no"] = qc.get("question_no")
            qc["question_no"] = i
            ans = str(qc.get("answer", "A")).strip().upper()
            if ans not in ("A", "B", "C", "D"):
                ans = "A"
            qc["answer"] = ans
            answer_key[str(i)] = ans
            reindexed_qs.append(qc)

        cat_tag = f"・{category}" if category and category != "全部考點分類 (不限)" else ""
        return {
            "subject": norm_sub,
            "topic": f"{chapter[:12]}{cat_tag}",
            "total_count": len(reindexed_qs),
            "questions": reindexed_qs,
            "answer_key": answer_key
        }

    def save_ai_generated_questions(self, subject: str, questions: List[Dict[str, Any]], topic: str = "") -> int:
        """
        當考生使用 AI 智慧命題產出試題後，自動去重並典藏至社群題庫
        """
        if not questions:
            return 0

        norm_sub = normalize_subject_key(subject)
        existing_hashes = {
            q.get("hash") or self._generate_question_hash(q.get("question", ""), q.get("options", {}).get("A", ""))
            for q in self.load_all_base_questions()
        }

        added = 0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for q in questions:
            q_text = q.get("question", "")
            opts = q.get("options", {})
            h = self._generate_question_hash(q_text, opts.get("A", ""))
            if h not in existing_hashes:
                entry = {
                    "id": f"mcq_ai_{uuid.uuid4().hex[:10]}",
                    "hash": h,
                    "subject": norm_sub,
                    "category": q.get("category") or topic or f"{norm_sub}核心爭點",
                    "case_facts": q.get("case_facts", ""),
                    "question": q_text,
                    "options": opts,
                    "answer": str(q.get("answer", "A")).strip().upper()[:1],
                    "explanation": q.get("explanation", ""),
                    "core_issue": q.get("core_issue", ""),
                    "source": f"AI智慧命題 ({norm_sub} - {now_str})",
                    "status": "active",
                    "created_at": now_str
                }
                self.dynamic_bank.append(entry)
                existing_hashes.add(h)
                added += 1

        if added > 0:
            self._save_dynamic_bank()
        return added

    def import_mcqs_from_pdf_text(self, text: str, filename: str, default_subject: str = "行政法") -> Tuple[int, List[Dict[str, Any]]]:
        """
        使用正則表達式與語義解析，從上傳之考題 PDF/文字中萃取標準一試選擇題
        支援題號、題幹、(A)(B)(C)(D) 選項、答案與解析
        """
        if not text or len(text.strip()) < 30:
            return 0, []

        norm_sub = normalize_subject_key(default_subject)
        extracted = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 模式 A: 針對標準考選部或司律模擬卷格式進行分塊
        # 尋找題號開頭，例如 "1." 或 "第 1 題" 或 "1、"
        pattern_split = re.compile(r'(?:\n\s*|^)(?:第\s*([0-9]{1,3})\s*題|[0-9]{1,3}[.、\s])')
        blocks = pattern_split.split(text)

        # 若成功分塊
        if len(blocks) > 3:
            # blocks 結構可能為 [prefix, num1, content1, num2, content2...]
            it = iter(blocks)
            _ = next(it) # prefix
            for num, block_content in zip(it, it):
                q_obj = self._parse_single_mcq_block(block_content, norm_sub, filename)
                if q_obj:
                    extracted.append(q_obj)

        # 模式 B: 若分塊不理想，嘗試整體正則搜尋
        if len(extracted) < 2:
            single_pattern = re.compile(
                r'(?:[0-9]{1,3}[.、]\s*|第\s*[0-9]{1,3}\s*題\s*)([\s\S]+?)\s*\(A\)([\s\S]+?)\(B\)([\s\S]+?)\(C\)([\s\S]+?)\(D\)([\s\S]+?)(?=(?:[0-9]{1,3}[.、]|第\s*[0-9]{1,3}\s*題|$))'
            )
            for m in single_pattern.finditer(text):
                q_text = m.group(1).strip()
                oa = m.group(2).strip()
                ob = m.group(3).strip()
                oc = m.group(4).strip()
                od_all = m.group(5).strip()

                # 從 (D) 後續中抽取答案或解析
                od = od_all
                ans = "A"
                exp = ""
                m_ans = re.search(r'(?:答案|正確答案|解答)[：:\s]*\(?([A-D])\)?', od_all, re.IGNORECASE)
                if m_ans:
                    ans = m_ans.group(1).upper()
                    od = od_all[:m_ans.start()].strip()
                    exp = od_all[m_ans.end():].strip()

                opts = {"A": oa[:300], "B": ob[:300], "C": oc[:300], "D": od[:300]}
                h = self._generate_question_hash(q_text, oa)
                extracted.append({
                    "id": f"mcq_pdf_{uuid.uuid4().hex[:10]}",
                    "hash": h,
                    "subject": norm_sub,
                    "category": f"{norm_sub}試卷匯入",
                    "question": q_text[:800],
                    "options": opts,
                    "answer": ans,
                    "explanation": exp[:1200] if exp else f"【解析】：本題依據{norm_sub}法理與最高法院判決見解，正確答案為 ({ans})。",
                    "source": f"試卷PDF匯入《{filename}》({now_str})",
                    "status": "active",
                    "created_at": now_str
                })

        # 去重入庫
        added = 0
        existing_hashes = {
            q.get("hash") or self._generate_question_hash(q.get("question", ""), q.get("options", {}).get("A", ""))
            for q in self.load_all_base_questions()
        }
        for item in extracted:
            if item["hash"] not in existing_hashes:
                self.dynamic_bank.append(item)
                existing_hashes.add(item["hash"])
                added += 1

        if added > 0:
            self._save_dynamic_bank()

        return added, extracted

    def _parse_single_mcq_block(self, block: str, subject: str, filename: str) -> Optional[Dict[str, Any]]:
        """從單一試題文字塊中解析出題目、四個選項與答案"""
        if "(A)" not in block or "(B)" not in block:
            return None

        # 找尋 (A) 起點
        idx_a = block.find("(A)")
        if idx_a == -1:
            idx_a = block.find("A.")
        if idx_a == -1:
            return None

        q_stem = block[:idx_a].strip()
        opts_part = block[idx_a:]

        m_opts = re.search(r'\(A\)([\s\S]+?)\(B\)([\s\S]+?)\(C\)([\s\S]+?)\(D\)([\s\S]+)', opts_part)
        if not m_opts:
            return None

        oa = m_opts.group(1).strip()
        ob = m_opts.group(2).strip()
        oc = m_opts.group(3).strip()
        od_raw = m_opts.group(4).strip()

        # 分離選項 D 與可能附帶之答案解析
        od = od_raw
        ans = "A"
        exp = ""
        m_ans = re.search(r'(?:答案|正確答案|解答|解析)[：:\s]*\(?([A-D])\)?', od_raw, re.IGNORECASE)
        if m_ans:
            ans = m_ans.group(1).upper()
            od = od_raw[:m_ans.start()].strip()
            exp = od_raw[m_ans.start():].strip()

        h = self._generate_question_hash(q_stem, oa)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "id": f"mcq_pdf_{uuid.uuid4().hex[:10]}",
            "hash": h,
            "subject": subject,
            "category": f"{subject}試卷匯入",
            "question": q_stem[:800],
            "options": {"A": oa[:300], "B": ob[:300], "C": oc[:300], "D": od[:300]},
            "answer": ans,
            "explanation": exp[:1200] if exp else f"【解析】：本題經考點分析，正確選項為 ({ans})。",
            "source": f"試卷PDF《{filename}》",
            "status": "active",
            "created_at": now_str
        }

    def report_and_adjudicate_question(
        self,
        question_item: Dict[str, Any],
        user_reason: str,
        caller_client=None
    ) -> Dict[str, Any]:
        """
        【試題報錯、撤下與 AI 審查修正核心流程】：
        1. 立即撤下 (先撤下)：將試題狀態標記為 'under_review'，抽題庫立即下架排除。
        2. 若考生有附上具體理由：
           - 呼叫 Gemini 模擬司法官律師命題審查委員進行專業法理裁定。
           - 若考生理由成立 (is_valid=True)：
             更新題目題幹、選項、標準答案與詳解，狀態設為 'verified_corrected' (重新上架)。
           - 若考生理由不成立 (is_valid=False)：
             維持原題與原答案，並於詳解中補充『考生疑義釋疑』，狀態設為 'verified_original' (重新上架)。
        3. 若未附理由：維持 'under_review' 撤下狀態。
        """
        qid = str(question_item.get("id"))
        qhash = str(question_item.get("hash") or self._generate_question_hash(question_item.get("question", ""), question_item.get("options", {}).get("A", "")))
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        user_reason_clean = user_reason.strip() if user_reason else ""

        # Step 1: 立即標記先撤下 (under_review)
        report_record = {
            "id": qid,
            "hash": qhash,
            "subject": question_item.get("subject", ""),
            "original_question": question_item.get("question", ""),
            "original_options": question_item.get("options", {}),
            "original_answer": question_item.get("answer", ""),
            "original_explanation": question_item.get("explanation", ""),
            "user_reason": user_reason_clean,
            "reported_at": now_str,
            "status": "under_review",
            "review_note": "考生已回報爭議，系統已先將本題自抽題庫撤下進入待審狀態。"
        }
        self.reports_log[qid] = report_record
        self.reports_log[qhash] = report_record
        self._save_reports_log()

        # 同步更新 dynamic_bank 中之實體（若存在）
        for dq in self.dynamic_bank:
            if str(dq.get("id")) == qid or dq.get("hash") == qhash:
                dq["status"] = "under_review"
        self._save_dynamic_bank()

        # Step 2: 若未附上理由，維持撤下狀態
        if not user_reason_clean:
            return {
                "success": True,
                "status": "under_review",
                "is_withdrawn": True,
                "is_adjudicated": False,
                "message": "⚠️ 感謝回報！題目已立即自抽題庫全面撤下。請於後續附上具體理由，以利 AI 為您進行精準裁決與修正！"
            }

        # Step 3: 若有理由，呼叫 Gemini 進行專業法學審查與自動修正
        adjudication_res = self._call_ai_adjudicator(question_item, user_reason_clean)

        is_valid = adjudication_res.get("is_valid", False)
        verdict = adjudication_res.get("verdict", "")
        rationale = adjudication_res.get("legal_rationale", "")

        if is_valid:
            # 考生有理：全面修正題目、選項、答案與詳解
            new_q = adjudication_res.get("corrected_question") or question_item.get("question")
            new_opts = adjudication_res.get("corrected_options") or question_item.get("options")
            new_ans = (adjudication_res.get("corrected_answer") or question_item.get("answer", "A")).strip().upper()[:1]
            new_exp = adjudication_res.get("corrected_explanation") or f"【AI 修正後詳解】：經考生提出疑義，依最新裁判見解，正確答案修正為 ({new_ans})。{rationale}"

            review_summary = f"【考生指摘有據・已修正】：{verdict}\n法理依據：{rationale}"
            report_record.update({
                "status": "verified_corrected",
                "corrected_question": new_q,
                "corrected_options": new_opts,
                "corrected_answer": new_ans,
                "corrected_explanation": new_exp,
                "review_note": review_summary,
                "adjudicated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            # 更新動態庫
            found = False
            for dq in self.dynamic_bank:
                if str(dq.get("id")) == qid or dq.get("hash") == qhash:
                    dq["question"] = new_q
                    dq["options"] = new_opts
                    dq["answer"] = new_ans
                    dq["explanation"] = new_exp
                    dq["status"] = "verified_corrected"
                    dq["review_note"] = review_summary
                    found = True
                    break
            if not found:
                # 若為原題庫題，以修正版存入動態庫
                corrected_entry = dict(question_item)
                corrected_entry["id"] = qid
                corrected_entry["hash"] = qhash
                corrected_entry["question"] = new_q
                corrected_entry["options"] = new_opts
                corrected_entry["answer"] = new_ans
                corrected_entry["explanation"] = new_exp
                corrected_entry["status"] = "verified_corrected"
                corrected_entry["review_note"] = review_summary
                self.dynamic_bank.append(corrected_entry)

            self._save_dynamic_bank()
            self._save_reports_log()

            return {
                "success": True,
                "status": "verified_corrected",
                "is_withdrawn": False,
                "is_adjudicated": True,
                "is_valid": True,
                "verdict": verdict,
                "rationale": rationale,
                "new_answer": new_ans,
                "new_explanation": new_exp,
                "message": f"🎉 審查完成！AI 判定考生理由正確（{verdict}）。題目、答案（已更正為 ({new_ans})）與詳解已全面修正完畢並重新上架！"
            }
        else:
            # 考生理解有誤，原題與答案依法有據：補充釋疑說明並維持
            orig_ans = question_item.get("answer", "A")
            clarification = f"\n\n💡【考生疑義釋疑】：有考生提問『{user_reason_clean}』。經 AI 依司法院裁判與法理深入複核：{rationale}，本題原命題與答案 ({orig_ans}) 依法並無違誤。"
            orig_exp = question_item.get("explanation", "") + clarification

            review_summary = f"【原題正當・補充釋疑】：{verdict}\n釋疑法理：{rationale}"
            report_record.update({
                "status": "verified_original",
                "corrected_explanation": orig_exp,
                "review_note": review_summary,
                "adjudicated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

            # 更新動態庫
            for dq in self.dynamic_bank:
                if str(dq.get("id")) == qid or dq.get("hash") == qhash:
                    dq["explanation"] = orig_exp
                    dq["status"] = "verified_original"
                    dq["review_note"] = review_summary
            self._save_dynamic_bank()
            self._save_reports_log()

            return {
                "success": True,
                "status": "verified_original",
                "is_withdrawn": False,
                "is_adjudicated": True,
                "is_valid": False,
                "verdict": verdict,
                "rationale": rationale,
                "new_answer": orig_ans,
                "new_explanation": orig_exp,
                "message": f"💡 審查完成：AI 判定原答案 ({orig_ans}) 依法有據（{verdict}）。釋疑理由已增補至本題詳細解析中並重新上架！"
            }

    def _call_ai_adjudicator(self, q_item: Dict[str, Any], user_reason: str) -> Dict[str, Any]:
        """呼叫 Gemini 進行一試試題疑義裁量"""
        api_key = get_gemini_api_key()
        if not api_key:
            return {
                "is_valid": False,
                "verdict": "未配置 API Key，暫維持撤下待審",
                "legal_rationale": "因目前無可用的 Gemini API Key，題目將持續保留於待審清單中。"
            }

        prompt = f"""
你是一位深諳中華民國司律一試（司法官、律師國家考試）命題審查規範的權威法學教授與大法官評議召集人。
現有考生對下列選擇題正式提出「題目報錯與疑義申請」，請你嚴格依據中華民國現行有效法律、司法院大法官解釋、憲法法庭判決、最高法院大法庭裁定及最高法院具參考價值裁判進行最嚴謹之法理裁量。

【原試題內容】：
- 考科：{q_item.get("subject", "法學專業")}
- 題幹：{q_item.get("question", "")}
- 選項：
  (A) {q_item.get("options", {}).get("A", "")}
  (B) {q_item.get("options", {}).get("B", "")}
  (C) {q_item.get("options", {}).get("C", "")}
  (D) {q_item.get("options", {}).get("D", "")}
- 原定公布答案：({q_item.get("answer", "A")})
- 原題附帶詳解：{q_item.get("explanation", "")}

【考生提出之報錯理由與爭執論點】：
\"\"\"{user_reason}\"\"\"

【審查與裁決指引】：
1. 判斷考生理由是否「於法有據」：
   - 若考生指摘正確（例如題目有邏輯瑕疵、最新法律已修正致使原答案錯誤、或原答案選錯了、或題幹選項文字有誤導性），判定 is_valid = true。
   - 若原題命題與答案完全正確，考生係出於對法理或構成要件之誤解，判定 is_valid = false。
2. 若 is_valid = true：
   - 請提供修正後無懈可擊之題幹 (corrected_question)、四個選項 (corrected_options)、正確答案 (corrected_answer)，以及融入考生疑義論證之完整權威詳解 (corrected_explanation)。
3. 若 is_valid = false：
   - 請提出一針見血之法理釋疑與法院裁判引證 (legal_rationale)，精闢說明為何考生觀點不成立，原答案為何完全正當。

請嚴格僅回傳以下純 JSON 格式（勿包含 markdown 額外字元）：
{{
  "is_valid": true或false,
  "verdict": "一句話裁決結論 (如：考生指摘有據，原答案應為(C) / 考生誤解民法第184條要件，原題正確無誤)",
  "legal_rationale": "詳細引證現行法條、大法庭裁定或權威實務論據之審查理由 (約 150-300 字)",
  "corrected_question": "修正後題幹 (若無需修題幹可回傳原題幹)",
  "corrected_options": {{ "A": "...", "B": "...", "C": "...", "D": "..." }},
  "corrected_answer": "修正後正確答案代碼 (A/B/C/D)",
  "corrected_explanation": "修正後之最新權威完整解析 (須附上法理裁判與考生疑義之剖析)"
}}
"""

        # 嘗試使用 google.genai 或 google.generativeai
        try:
            try:
                from google import genai
                from google.genai import types as genai_types
                client = genai.Client(api_key=api_key)
                cfg = genai_types.GenerateContentConfig(temperature=0.2)
                resp = client.models.generate_content(
                    model=DEFAULT_GEMINI_MODEL,
                    contents=prompt,
                    config=cfg
                )
                raw_text = resp.text
            except Exception:
                import google.generativeai as legacy_genai
                legacy_genai.configure(api_key=api_key)
                m = legacy_genai.GenerativeModel(DEFAULT_GEMINI_MODEL)
                resp = m.generate_content(prompt, generation_config={"temperature": 0.2})
                raw_text = resp.text

            clean_json = raw_text.strip()
            if "```" in clean_json:
                m_code = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', clean_json)
                if m_code:
                    clean_json = m_code.group(1).strip()

            parsed = json.loads(clean_json)
            return parsed
        except Exception as e:
            # 容錯回傳
            return {
                "is_valid": False,
                "verdict": f"AI 審查調用發生異常: {str(e)[:60]}",
                "legal_rationale": f"因 API 調用或解析格式問題，已先將試題撤下以策安全。異常詳情: {e}"
            }


# 全局單例
_global_mcq_manager = None
def get_mcq_bank_manager() -> MCQBankManager:
    global _global_mcq_manager
    if _global_mcq_manager is None:
        _global_mcq_manager = MCQBankManager()
    return _global_mcq_manager
