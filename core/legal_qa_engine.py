"""
專屬法學全能智慧問答與特化檢索引擎 (Dedicated Legal Search & Q&A Engine)
支援專為司律考試與實務法學打造之自然語言單一萬能檢索：
1. 🌟 全方位通用諮詢 (跨領域民刑、行政、商事法綜合法理剖析)
2. 📜 條文歸屬速查 ("這情況適用哪一條？"、法規條號定位、構成要件拆解、相鄰易混淆法條辨析)
3. ⚖️ 法學爭點深析 (司法實務通說 vs 學說爭鳴、大法庭裁定、憲法法庭判決、IRAC 破題模板)
4. 🧮 法律金錢與損害賠償精算 (車輛定率遞減法/直線法折舊、勞退新制資遣費、夫妻剩餘財產、遺產特留分、法定遲延利息)
5. 💬 生活與實務法律諮詢 (六大維度評析、存證信函生成、調解要旨生成、時效警示)
"""

import os
import sys
import json
import re
from typing import Dict, Any, List, Optional, Tuple

try:
    from google import genai
    from google.genai import types as genai_types
    USE_MODERN_GENAI = True
    HAS_GENAI = True
except ImportError:
    try:
        import google.generativeai as legacy_genai
        USE_MODERN_GENAI = False
        HAS_GENAI = True
    except ImportError:
        HAS_GENAI = False
        USE_MODERN_GENAI = False

try:
    from config import get_gemini_api_key, DEFAULT_GEMINI_MODEL, get_gemini_models_to_try
except Exception:
    def get_gemini_api_key():
        import os
        return os.environ.get("GEMINI_API_KEY", "")
    DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
    def get_gemini_models_to_try():
        return ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]

# 檢索意圖模式
QUERY_TYPES = [
    "🌟 智慧綜合判斷 (全自動意圖辨識)",
    "📜 條文歸屬速查 (這是哪一條・構成要件・相鄰法條辨析)",
    "⚖️ 法學爭點深析 (實務通說 vs 學說爭鳴・大法庭裁定・作答架構)",
    "🧮 法律金錢與例題精算 (損害賠償・零件折舊・資遣費・遺產特留分)",
    "💬 生活與實務法律諮詢 (六大維度・證據清單・救濟行動指南)"
]

# 常用法律領域分類
LEGAL_CONSULTATION_DOMAINS = [
    "🌟 自動偵測 (全領域綜合剖析)",
    "🏠 不動產與房屋租賃 (租屋修繕、押金沒收、提前終止、買賣瑕疵)",
    "🚗 交通事故與侵權理賠 (車禍初判表、過失傷害、修車折舊、精神慰撫金)",
    "💼 勞資爭議與勞動權益 (違法解僱、資遣費、加班費、職災補償、離職交接)",
    "💰 金錢借貸與債權保障 (借據本票、本票裁定、支付命令、強制執行、消滅時效)",
    "🛍️ 消費爭議與網路購物 (消保法7天猶豫期、定型化契約無效、商品瑕疵退換貨)",
    "🛡️ 刑法告訴與名譽保障 (妨害名譽、公然侮辱、誹謗、詐欺受害、警示帳戶申訴)",
    "👨‍👩‍👧 婚姻家事與遺產繼承 (裁判離婚、子女親權監護、扶養費、遺產分配特留分)",
    "🏢 公寓大廈與鄰里糾紛 (樓上漏水容忍修繕、噪音擾鄰、管委會規約爭議)",
    "📜 商業契約與智慧財產 (合約審閱修訂、商標著作侵權、營業秘密、競業禁止)"
]

USER_STANDPOINTS = [
    "⚖️ 客觀中立立場 (全面衡平評估法理與雙方勝算)",
    "🛡️ 權利受損方 / 被告 / 弱勢方 (防禦抵抗、自保抗辯與免責主張)",
    "⚔️ 權利主張方 / 原告 / 求償方 (積極求償、權利行使與法律進攻)"
]

OUTPUT_MODES = [
    "📑 完整專業法律諮詢意見書 (定性・條文・權利・證據・流程・時效)",
    "⚡ 核心重點精簡快答 (白話摘要・能要什麼・第一步該做什麼)"
]

# ----------------- 確定性純 Python 法律金錢精算函數 -----------------

def calculate_vehicle_depreciation(
    part_cost: float,
    labor_cost: float,
    age_years: int,
    age_months: int,
    vehicle_type: str = "自用小客車 (耐用年數5年，年折舊率 0.369)",
    method: str = "定率遞減法 (每年折舊率計算，殘值底線 10%)",
    comparative_negligence_pct: float = 0.0
) -> Dict[str, Any]:
    """
    依行政院固定資產耐用年數表與最高法院 77 年度第九次民事庭會議決議精算車損折舊。
    零件折舊，工資不予折舊。殘值保底 10%。
    """
    # 決定耐用年數與定率遞減率
    if "營業" in vehicle_type or "計程車" in vehicle_type:
        useful_years = 4
        rate = 0.438
    elif "機車" in vehicle_type:
        useful_years = 3
        rate = 0.536
    elif "貨車" in vehicle_type:
        useful_years = 4
        rate = 0.438
    else:  # 自用小客車
        useful_years = 5
        rate = 0.369

    min_residual_limit = round(part_cost * 0.1, 2)
    steps = []
    current_value = part_cost

    if "定率" in method or "遞減" in method:
        # 定率遞減法
        for y in range(1, age_years + 1):
            dep = round(current_value * rate, 2)
            current_value = round(current_value - dep, 2)
            steps.append(f"第 {y} 年折舊：折舊額 NT${dep:,.2f}，未折舊餘額 NT${current_value:,.2f}")

        if age_months > 0:
            month_dep = round(current_value * rate * (age_months / 12.0), 2)
            current_value = round(current_value - month_dep, 2)
            steps.append(f"未滿 1 年之 {age_months} 個月折舊：折舊額 NT${month_dep:,.2f}，未折舊餘額 NT${current_value:,.2f}")

        # 殘值底線保護 (依所得稅法施行細則第51-1條，殘值不低於 10%)
        if current_value < min_residual_limit:
            steps.append(f"⚠️ 經計算零件餘額 NT${current_value:,.2f} 低於法定殘值底線（取得原價 10% 即 NT${min_residual_limit:,.2f}），依法以法定殘值 NT${min_residual_limit:,.2f} 計入！")
            final_part_value = min_residual_limit
        else:
            final_part_value = current_value
    else:
        # 平均法 (直線法)
        total_months = age_years * 12 + age_months
        useful_months = useful_years * 12
        residual = round(part_cost / (useful_years + 1), 2)
        yearly_dep = round((part_cost - residual) / useful_years, 2)
        monthly_dep = round(yearly_dep / 12.0, 2)

        steps.append(f"法定預留殘值（取得原價 / (耐用年數 + 1)）：NT${residual:,.2f}")
        steps.append(f"每年折舊額：NT${yearly_dep:,.2f}，每月折舊額：NT${monthly_dep:,.2f}")

        if total_months >= useful_months:
            steps.append(f"行車年資 {age_years} 年 {age_months} 月已超過耐用年限 {useful_years} 年，零件僅以法定殘值 NT${residual:,.2f} 計入。")
            final_part_value = residual
        else:
            accum_dep = round(monthly_dep * total_months, 2)
            final_part_value = round(part_cost - accum_dep, 2)
            steps.append(f"累積 {total_months} 個月折舊額：NT${accum_dep:,.2f}，折舊後零件價值：NT${final_part_value:,.2f}")

    part_depreciation_total = round(part_cost - final_part_value, 2)
    total_claim_before_negligence = round(final_part_value + labor_cost, 2)
    
    negligence_factor = max(0.0, min(100.0, comparative_negligence_pct))
    final_award = round(total_claim_before_negligence * (1.0 - (negligence_factor / 100.0)), 2)

    return {
        "part_original": part_cost,
        "part_depreciation_total": part_depreciation_total,
        "part_final_value": final_part_value,
        "labor_cost": labor_cost,
        "subtotal_before_negligence": total_claim_before_negligence,
        "comparative_negligence_pct": negligence_factor,
        "final_award": final_award,
        "steps": steps,
        "legal_basis": "民法第196條（物被毀損之損害賠償）、民法第213條至第215條、最高法院77年度第九次民事庭會議決議、行政院固定資產耐用年數表。"
    }

def calculate_severance_pay(
    monthly_wage: float,
    years: int,
    months: int,
    days: int,
    has_advance_notice: bool = False
) -> Dict[str, Any]:
    """
    依勞工退休金條例第 12 條（勞退新制）及勞基法第 16 條預告期間工資精算資遣費。
    """
    tenure_years = years + (months / 12.0) + (days / 365.0)
    # 勞退新制：每滿 1 年發給 0.5 個月平均工資，未滿 1 年以比例計，最高以 6 個月為限
    base_factor = round(tenure_years * 0.5, 4)
    capped_factor = min(base_factor, 6.0)
    severance_amount = round(capped_factor * monthly_wage, 2)

    # 預告期間工資（勞動基準法第 16 條）
    daily_wage = round(monthly_wage / 30.0, 2)
    notice_days = 0
    if not has_advance_notice:
        if tenure_years < (3.0 / 12.0):
            notice_days = 0
        elif tenure_years < 1.0:
            notice_days = 10
        elif tenure_years < 3.0:
            notice_days = 20
        else:
            notice_days = 30
    notice_pay = round(daily_wage * notice_days, 2)
    total_due = round(severance_amount + notice_pay, 2)

    return {
        "monthly_wage": monthly_wage,
        "tenure_str": f"{years} 年 {months} 個月 {days} 天 (約 {tenure_years:.2f} 年)",
        "base_factor": base_factor,
        "capped_factor": capped_factor,
        "severance_amount": severance_amount,
        "notice_days": notice_days,
        "notice_pay": notice_pay,
        "total_due": total_due,
        "legal_basis": "勞工退休金條例第12條（新制資遣費）、勞動基準法第16條（預告期間工資）、勞動基準法第17條。"
    }

def calculate_marital_property_division(
    husband_assets: float,
    husband_debts: float,
    husband_exempt: float,
    wife_assets: float,
    wife_debts: float,
    wife_exempt: float
) -> Dict[str, Any]:
    """
    民法第 1030 條之 1 夫妻法定財產制剩餘財產差額分配精算。
    婚後財產扣除婚後負債及無償取得財產（繼承、無償贈與、慰撫金）。
    """
    h_net = max(0.0, round(husband_assets - husband_debts - husband_exempt, 2))
    w_net = max(0.0, round(wife_assets - wife_debts - wife_exempt, 2))
    diff = round(abs(h_net - w_net), 2)
    transfer_amount = round(diff / 2.0, 2)

    if h_net > w_net:
        giver = "夫 (先生)"
        receiver = "妻 (太太)"
    elif w_net > h_net:
        giver = "妻 (太太)"
        receiver = "夫 (先生)"
    else:
        giver = "雙方相等"
        receiver = "無須給付"
        transfer_amount = 0.0

    return {
        "husband_net": h_net,
        "wife_net": w_net,
        "difference": diff,
        "transfer_amount": transfer_amount,
        "giver": giver,
        "receiver": receiver,
        "legal_basis": "民法第1030條之1（剩餘財產分配請求權）、民法第1017條。"
    }

def calculate_inheritance_shares(
    estate_total: float,
    has_spouse: bool,
    order: int,  # 1: 直系卑親屬(子女), 2: 父母, 3: 兄弟姊妹, 4: 祖父母, 0: 無其他順序
    heir_count: int
) -> Dict[str, Any]:
    """
    民法第 1144 條法定應繼分與第 1223 條特留分精算。
    """
    if heir_count <= 0 and order != 0:
        heir_count = 1

    heirs_summary = []

    if has_spouse:
        if order == 1:
            # 與子女均分
            total_heads = heir_count + 1
            sp_fraction = 1.0 / total_heads
            sp_amount = round(estate_total * sp_fraction, 2)
            sp_reserved = round(sp_amount * 0.5, 2)
            heirs_summary.append({
                "role": "配偶",
                "fraction": f"1/{total_heads}",
                "amount": sp_amount,
                "reserved": sp_reserved,
                "note": "與第一順序均分，特留分為應繼分之 1/2"
            })
            child_fraction = 1.0 / total_heads
            child_amount = round(estate_total * child_fraction, 2)
            child_reserved = round(child_amount * 0.5, 2)
            for i in range(1, heir_count + 1):
                heirs_summary.append({
                    "role": f"子女 #{i}",
                    "fraction": f"1/{total_heads}",
                    "amount": child_amount,
                    "reserved": child_reserved,
                    "note": "第一順序繼承人，特留分為應繼分之 1/2"
                })
        elif order == 2:
            # 配偶 1/2，父母 1/2
            sp_amount = round(estate_total * 0.5, 2)
            sp_reserved = round(sp_amount * 0.5, 2)
            heirs_summary.append({
                "role": "配偶",
                "fraction": "1/2",
                "amount": sp_amount,
                "reserved": sp_reserved,
                "note": "與第二順序同為繼承，配偶應繼分 1/2"
            })
            p_total = estate_total * 0.5
            p_each_amount = round(p_total / heir_count, 2)
            p_each_reserved = round(p_each_amount * 0.5, 2)
            for i in range(1, heir_count + 1):
                heirs_summary.append({
                    "role": f"父母 #{i}",
                    "fraction": f"1/{2 * heir_count}",
                    "amount": p_each_amount,
                    "reserved": p_each_reserved,
                    "note": "第二順序繼承人，特留分為應繼分之 1/2"
                })
        elif order == 3:
            # 配偶 1/2，兄弟姊妹 1/2
            sp_amount = round(estate_total * 0.5, 2)
            sp_reserved = round(sp_amount * 0.5, 2)
            heirs_summary.append({
                "role": "配偶",
                "fraction": "1/2",
                "amount": sp_amount,
                "reserved": sp_reserved,
                "note": "與第三順序同為繼承，配偶應繼分 1/2"
            })
            sib_total = estate_total * 0.5
            sib_each_amount = round(sib_total / heir_count, 2)
            sib_each_reserved = round(sib_each_amount * (1.0 / 3.0), 2)
            for i in range(1, heir_count + 1):
                heirs_summary.append({
                    "role": f"兄弟姊妹 #{i}",
                    "fraction": f"1/{2 * heir_count}",
                    "amount": sib_each_amount,
                    "reserved": sib_each_reserved,
                    "note": "第三順序繼承人，特留分為應繼分之 1/3"
                })
        elif order == 4:
            # 配偶 2/3，祖父母 1/3
            sp_amount = round(estate_total * (2.0 / 3.0), 2)
            sp_reserved = round(sp_amount * 0.5, 2)
            heirs_summary.append({
                "role": "配偶",
                "fraction": "2/3",
                "amount": sp_amount,
                "reserved": sp_reserved,
                "note": "與第四順序同為繼承，配偶應繼分 2/3"
            })
            gp_total = estate_total * (1.0 / 3.0)
            gp_each_amount = round(gp_total / heir_count, 2)
            gp_each_reserved = round(gp_each_amount * (1.0 / 3.0), 2)
            for i in range(1, heir_count + 1):
                heirs_summary.append({
                    "role": f"祖父母 #{i}",
                    "fraction": f"1/{3 * heir_count}",
                    "amount": gp_each_amount,
                    "reserved": gp_each_reserved,
                    "note": "第四順序繼承人，特留分為應繼分之 1/3"
                })
        else:
            # 僅配偶一人單獨繼承
            sp_amount = round(estate_total, 2)
            sp_reserved = round(sp_amount * 0.5, 2)
            heirs_summary.append({
                "role": "配偶 (單獨繼承)",
                "fraction": "全部 (1/1)",
                "amount": sp_amount,
                "reserved": sp_reserved,
                "note": "無第一至四順序血親繼承人，由配偶全部繼承"
            })
    else:
        # 無配偶，由血親繼承人均分
        fraction_each = 1.0 / heir_count
        amount_each = round(estate_total * fraction_each, 2)
        reserved_ratio = 0.5 if order in (1, 2) else (1.0 / 3.0)
        reserved_each = round(amount_each * reserved_ratio, 2)
        order_names = {1: "子女 (直系血親卑親屬)", 2: "父母", 3: "兄弟姊妹", 4: "祖父母"}
        name_prefix = order_names.get(order, "繼承人")
        for i in range(1, heir_count + 1):
            heirs_summary.append({
                "role": f"{name_prefix} #{i}",
                "fraction": f"1/{heir_count}",
                "amount": amount_each,
                "reserved": reserved_each,
                "note": f"特留分為應繼分之 {'1/2' if reserved_ratio == 0.5 else '1/3'}"
            })

    return {
        "estate_total": estate_total,
        "heirs_summary": heirs_summary,
        "legal_basis": "民法第1138條（法定繼承人順序）、民法第1144條（配偶應繼分）、民法第1223條（特留分比例）。"
    }

def calculate_statutory_interest(
    principal: float,
    days: int,
    annual_rate_pct: float = 5.0
) -> Dict[str, Any]:
    """
    民法第 203 條法定年息 5% 遲延利息精算。
    """
    interest_amount = round(principal * (annual_rate_pct / 100.0) * (days / 365.0), 2)
    total_amount = round(principal + interest_amount, 2)
    return {
        "principal": principal,
        "days": days,
        "annual_rate_pct": annual_rate_pct,
        "interest_amount": interest_amount,
        "total_amount": total_amount,
        "legal_basis": "民法第203條（法定遲延利率年息5%）、民法第229條（給付遲延）、民法第233條。"
    }


class LegalQAEngine:
    """
    全方位通用法律智慧問答與全能檢索引擎
    """
    def __init__(self):
        self.api_key = get_gemini_api_key()

    def detect_query_intent(self, text: str) -> str:
        """
        全自動法學意圖特化辨識與定性：
        - 條文歸屬定位 ("這是哪一條")
        - 法學爭點深析 ("實務通說 vs 學說")
        - 法律金錢與例題精算 ("折舊/資遣費/特留分算式")
        - 通用/生活法律諮詢
        """
        t = text.lower()
        # 1. 條文定位
        if any(k in t for k in ["哪一條", "何條", "條文是", "法條是", "第幾條", "法條依據是哪", "條文為何", "適用何條", "這是哪條", "條文代號", "法條名稱"]):
            return "📜 條文歸屬速查 (這是哪一條・構成要件・相鄰法條辨析)"
        # 2. 爭點深析
        if any(k in t for k in ["爭點", "學說", "實務見解", "通說", "有力說", "大法庭", "決議", "判例", "憲判", "爭鳴", "見解歧異", "折衷說", "有權處分", "無權處分", "保證人地位", "不作為犯", "利益衡量", "irac", "擬答"]):
            return "⚖️ 法學爭點深析 (實務通說 vs 學說爭鳴・大法庭裁定・作答架構)"
        # 3. 金錢與損害賠償精算
        if any(k in t for k in ["計算", "算式", "試算", "多少錢", "折舊", "定率遞減", "直線法", "資遣費", "預告工資", "特留分", "應繼分", "剩餘財產", "年資", "月薪", "利息", "遲延利息", "本利和", "賠償多少", "幾成", "比例", "工資折舊", "扣抵"]):
            return "🧮 法律金錢與例題精算 (損害賠償・零件折舊・資遣費・遺產特留分)"
        # 4. 預設生活與實務法扶諮詢
        return "💬 生活與實務法律諮詢 (六大維度・證據清單・救濟行動指南)"

    def _call_model(self, prompt: str, temperature: float = 0.2) -> str:
        if not HAS_GENAI:
            return self._generate_offline_legal_fallback(prompt)

        models_to_try = get_gemini_models_to_try()
        last_error = None

        if USE_MODERN_GENAI:
            client = genai.Client(api_key=self.api_key) if self.api_key else genai.Client()
            for model_name in models_to_try:
                try:
                    resp = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=genai_types.GenerateContentConfig(
                            temperature=temperature,
                            max_output_tokens=4096
                        ) if hasattr(genai_types, 'GenerateContentConfig') else None
                    )
                    if resp and resp.text:
                        return resp.text
                except Exception as e:
                    last_error = e
                    continue
        else:
            if self.api_key:
                legacy_genai.configure(api_key=self.api_key)
            for model_name in models_to_try:
                try:
                    m = legacy_genai.GenerativeModel(model_name)
                    resp = m.generate_content(
                        prompt,
                        generation_config={"temperature": temperature, "max_output_tokens": 4096}
                    )
                    if resp and resp.text:
                        return resp.text
                except Exception as e:
                    last_error = e
                    continue

        return self._generate_offline_legal_fallback(prompt)

    def answer_legal_question(
        self,
        question: str,
        domain: str = "🌟 自動偵測 (全領域綜合剖析)",
        standpoint: str = "⚖️ 客觀中立立場 (全面衡平評估法理與雙方勝算)",
        output_mode: str = "📑 完整專業法律諮詢意見書 (定性・條文・權利・證據・流程・時效)",
        query_type: str = "🌟 智慧綜合判斷 (全自動意圖辨識)",
        history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        解答一般及進階法律問題，根據 query_type 自動切換至最合適之法學架構輸出。
        """
        if not question or not question.strip():
            return {
                "success": False,
                "error": "請輸入欲查詢或諮詢之法律問題、條文疑義、爭點或案件事實！",
                "content": ""
            }

        q_clean = question.strip()
        detected_domain = self.detect_question_domain(q_clean) if "自動偵測" in domain else domain
        
        # 決定實際檢索意圖
        actual_intent = self.detect_query_intent(q_clean) if "智慧綜合" in query_type or "全自動" in query_type else query_type

        history_context = ""
        if history and len(history) > 0:
            history_context = "【先前對話紀錄與追問脈絡】：\n"
            for h in history[-4:]:
                history_context += f"- 提問者: {h.get('question', '')}\n- 顧問回答重點: {h.get('answer', '')[:200]}...\n"
            history_context += "\n"

        # 針對不同意圖構建專屬 Prompt
        if "條文歸屬" in actual_intent or "哪一條" in actual_intent:
            prompt = f"""你是一名精通中華民國法典體系之高階法學導航專家。使用者正在詢問某特定生活事實、法律關係或交易行為「適用現行法律之哪一條條文」。
請針對該事實，以權威法學體系將適用條文精準定位，並進行要件拆解與相鄰條文辨析。

【使用者查詢事實或情境】：
{q_clean}

- 領域歸屬：{detected_domain}
- 諮詢立場：{standpoint}

{history_context}
請以繁體中文與台灣法學專業術語，依循以下標準架構進行權威條文定位解答：

### 🎯 一、精準核心適用法條 (Primary Statutory Provision)
- 明確列出主掌此行為之【法規全有名稱】、【具體條號】與【項款】（如：民法第811條動產附合於不動產、民法第184條第1項前段、消費者保護法第19條等）。
- 引述該條文最新修正之完整現行條文內容。

### 🧩 二、法定構成要件拆解與該當性 (Elements Analysis)
- 拆解該條文必備之核心構成要件：
  1. 主體要件（權利人與義務人身分限制）
  2. 客觀行為要件（具體客觀行為態樣）
  3. 主觀歸責要件（故意、重大過失或一般過失）
  4. 結果與因果關係（損害之發生或狀態改變）
- 涵攝說明使用者的案件事實是否滿足上述各要件。

### ⚡ 三、法定法律效果與請求權依據 (Legal Effects & Remedies)
- 該條文被引動後，當事人能主張哪些具體法律效果？（如：所有權歸屬、不當得利償還請求權、契約解除權、損害賠償、刑事追訴等）。
- 提示消滅時效或行使除斥期間（如：侵權行為2年、解除權6個月、一般債權15年）。

### 🔍 四、相鄰與易混淆條文對比辨析 (Adjacent Confusing Provisions)
- 列出實務與考試最容易混淆的 1~2 條相鄰條文（例如：動產附合 vs 混合 vs 加工；侵權行為 vs 不完全給付；背信罪 vs 詐欺罪）。
- 以條列或對照形式說明：為什麼本案適用本條，而非該相鄰條文？關鍵差異何在？

### 🏛️ 五、司法院實務權威指標字號 (Landmark Court Precedents)
- 提供 1~2 則最高法院確定判決字號、決議或大法庭裁定，說明司法實務對此法條之核心解釋心證。
"""

        elif "爭點深析" in actual_intent or "學說" in actual_intent:
            prompt = f"""你是一名具備最高法院大法庭調解心證與法研所講座級功力的權威法學論辯教授。使用者正在詢問一個具備重大實務或學說分歧之【法學核心爭點】。
請針對該爭點，進行深入之司法實務通說、各派學者理論爭鳴與 IRAC 作答模板剖析。

【使用者詢問之爭點或法律題目】：
{q_clean}

- 領域歸屬：{detected_domain}
- 諮詢立場：{standpoint}

{history_context}
請以繁體中文與台灣法學專業術語，嚴格依照以下學術與實務論辯架構輸出：

### 📌 一、爭點源起與法律問題核心 (Issue Identification)
- 提煉核心法理爭點（例如：條文文義盲區、價值衡平取捨、或社會新型態契約之定性爭議）。
- 指明相關核心法條與法益保護目的。

### 🏛️ 二、司法實務通說與最高法院統一見解 (Judicial Practice)
- 闡述最高法院民/刑事庭會議決議、大法庭裁定、或憲法法庭判決之主流立場。
- 完整引述具代表性裁判字號與其法理推論依據（如：保障交易安全、外觀法理、文義解釋極限等）。

### 📚 三、法學界通說與有力說爭鳴 (Academic Theories)
- **學說通說論點**：多數學者之看法與法理邏輯。
- **有力說 / 少數說論點**：著名學者（如王澤鑑、林山田、黃榮堅、陳敏、陳聰富等）之精闢見解與反對理由。

### ⚖️ 四、各說深入評析與綜合審查 (Comparative Analysis)
- 衡平比較實務說與學說之優劣利弊（法安定性 vs 實質正義 vs 交易效率）。
- 闡述當前法學演進趨勢。

### 💡 五、司法考試與實務作答 IRAC 三段論法模板 (IRAC Model Answer)
- 提供一段標準的【IRAC 擬答實戰範本】：
  - **Issue (爭點提出)**
  - **Rule (法條大前提與實務學說規範)**
  - **Application (案件事實精密涵攝)**
  - **Conclusion (最終結論定奪)**
"""

        elif "金錢" in actual_intent or "精算" in actual_intent:
            prompt = f"""你是一名精通臺灣民事賠償計算、勞資資遣計算、家事剩餘財產與遺產特留分之專業法學精算律師。
使用者提出了一道包含金額、數值、年資、車齡或傷損之具體法律例題，需要精確之算式推導、法律扣抵及最終金額定奪。

【使用者提供之金錢例題與案件事實】：
{q_clean}

- 領域歸屬：{detected_domain}
- 諮詢立場：{standpoint}

{history_context}
請以繁體中文與台灣法學專業術語，按以下步驟進行嚴謹數學與法理推導：

### 📋 一、金錢請求項目定性與法理依據 (Classification of Claims)
- 梳理題目中之各項金額請求（如：車損零件費、修車工資、醫療費用、工作損失、精神慰撫金、勞退新制資遣費、預告工資等）。
- 標明各項目之請求權法條基礎（如民法第196條、第193條、第195條、勞退條例第12條、民法第1030條之1等）。

### 📜 二、法院認可之法定標準與計算公式 (Statutory Formula & Standards)
- 詳細說明適用之法定標準（例如：行政院固定資產耐用年數表與定率遞減法折舊率、直線平均法、殘值10%保底原則、工資不折舊原則、過失相抵百分比、勞退新制每滿1年0.5個月等）。

### 🧮 三、逐步算式推導與代入運算 (Step-by-Step Mathematical Derivation)
- 一步一步列出詳細的數學算式、數值代入過程與計算結果：
  - [步驟一] ...
  - [步驟二] ...
  - [步驟三] ...
- 明確交代小數點與四捨五入處理。

### 📊 四、最終得請求 / 應給付金額彙整表 (Final Financial Summary Table)
- 以 Markdown 表格清晰呈現：項目名稱、原始主張金額、扣除或折舊額、法定應得淨額。
- 計算最終總金額（含過失相抵後之實得賠償額）。

### 💡 五、實務求償策略與法定利息計算提醒 (Strategic Advice & Interest)
- 提醒起訴或調解時之遲延利息（民法第203條年息5%，起算日通常為起訴狀繕本送達翌日或催告期滿翌日）。
- 提醒假扣押擔保金預估與裁判費徵收標準。
"""

        else:
            # 完整六大維度通用生活與實務法扶意見書
            prompt = f"""你是一名具備中華民國合格律師實務經驗、行政程序法理與最高法院判決心證精髓的高階法律諮詢顧問。
請針對當事人所提出之生活或實務法律問題，依據現行《中華民國法律》、《最高法院權威判決/大法庭裁定》及《司法實務通說》，提出專業、嚴謹且極具實務可操作性的法律意見。

【使用者諮詢案件資訊】：
- 法律問題事實：
{q_clean}

- 指定法律範疇：{detected_domain}
- 諮詢立場角度：{standpoint}
- 輸出模式：{output_mode}

{history_context}
請使用繁體中文（台灣法學專業術語），並嚴格按照以下六大標準結構進行深度剖析：

### 🎯 一、案件法律關係定性與爭端核心 (Legal Characterization)
- 精準定義當事人間之法律關係（民事契約關係、侵權責任、刑事犯罪告訴、行政裁罰或勞資關係）。
- 釐清爭議焦點本質與可能之法律責任歸屬。

### 📜 二、適用法律條文依據與實務見解 (Applicable Laws & Precedents)
- 具體列出所適用之中華民國現行法條（如：民法第OO條、勞動基準法第OO條、消費者保護法第OO條、刑法第OO條）。
- 引述條文關鍵構成要件，並引用實務指標裁判意旨、憲法法庭判決或最高法院大法庭裁定之重要見解。

### ⚖️ 三、權利主張、法律效果與抗辯評估 (Claims, Rights & Defenses)
- 站在指定立場（{standpoint}）評估：依法能主張哪些具體權利或請求權？能請求多少金額或何種法律效果？
- 分析相對人可能提出的法理抗辯（如：時效抗辯、過失相抵、契約免責條款無效、未催告等），以及我方應如何反駁拆招。

### 📋 四、關鍵證據清單與舉證責任 (Evidence & Burden of Proof)
- 詳列實務上進入調解或訴訟「最關鍵、最具決定性」的證據清單（如：LINE/通訊軟體對話截圖、銀行匯款單據、簽約正本、驗傷單/診斷書、監視器影像、車禍初判表等）。
- 提示舉證責任分配法則（民事訴訟法第277條本文）與保全證據之具體步驟。

### 🚀 五、實務救濟程序與分階段行動指南 (Action Roadmap & Remedies)
- 提供明確的下一步實務行動清單：
  1. 【階段一：自保與證據保全】
  2. 【階段二：正式協商與催告】（存證信函寄發要點）
  3. 【階段三：行政或調解途徑】（鄉鎮市區公所調解委員會、消保官申訴、勞動局勞資爭議調解）
  4. 【階段四：司法救濟程序】（聲請支付命令、本票裁定、提起民事訴訟/小額訴訟、提出刑事告訴附帶民事賠償）

### ⏳ 六、法定期限、時效警示與自律提醒 (Statute of Limitations & Crucial Deadlines)
- 列出本案致命的法律時效（例如：刑事告訴乃論6個月告訴期、民法侵權行為2年/10年時效、借貸買賣消滅時效、租約提前終止預告期）。
- 專業法學免責聲明：本分析係依當事人提供之事實簡述進行法理推論，如涉具體重大訴訟案情，仍應攜帶完整事證諮詢合格執業律師。
"""

        analysis_result = self._call_model(prompt)

        return {
            "success": True,
            "domain": detected_domain,
            "standpoint": standpoint,
            "output_mode": output_mode,
            "query_type": actual_intent,
            "question": q_clean,
            "content": analysis_result
        }

    def generate_legal_notice(
        self,
        question: str,
        legal_advice: str,
        sender_name: str = "【寄件人姓名】",
        receiver_name: str = "【相對人姓名/公司名稱】",
        deadline_days: int = 7
    ) -> str:
        """
        根據諮詢案件事實與法律分析，一鍵生成正式標準格式的「郵局存證信函」草稿
        """
        prompt = f"""請以專業臺灣執業律師之筆觸，針對以下法律爭議與法理分析，自動草擬一份符合中華民國郵局標準格式之【存證信函】：

【案件事實】：
{question}

【法學分析依據】：
{legal_advice[:1000]}

【發函基本資訊】：
- 寄件人：{sender_name}
- 相對人（收件人）：{receiver_name}
- 催告/限期履行天數：{deadline_days} 日內

【格式要求】：
1. 嚴格遵循郵局存證信函標準結構：
   - 寄件人、收件人及副本收件人欄位
   - 信函主旨（明確敘明要求目的，如：催告限期返還房屋租賃押金、催告給付工程尾款、依法解除契約通知等）
   - 事實經過說明（清晰、簡練、客觀陳述人、事、時、地、物）
   - 法律依據（精準引用法條，宣告若未於期限內履行將採取之法律途徑：民事訴訟、聲請強制執行、提起刑事告訴）
   - 限期催告結論（明確記載文到後 {deadline_days} 日內履行）
2. 語氣堅定、依法有據、用字嚴謹，直接可供當事人填妥住址後至郵局或線上存證信函系統寄發。
"""
        return self._call_model(prompt, temperature=0.1)

    def generate_mediation_summary(
        self,
        question: str,
        legal_advice: str
    ) -> str:
        """
        一鍵生成鄉鎮市區公所調解委員會【民事/刑事調解聲請書】要旨與調解方案建議
        """
        prompt = f"""請依據以下案件事實與法學分析，草擬一份提交予【鄉鎮市區調解委員會】的調解聲請要旨與和解談判方案建議：

【案件事實】：
{question}

【法理分析】：
{legal_advice[:1000]}

【輸出架構】：
1. 聲請調解事由（明確案由，如：車禍損害賠償事件、房屋租賃押金返還事件、買賣價金爭議）
2. 聲請調解標的與請求金額/條件（明確列出我方請求相對人給付之具體項目與新臺幣金額）
3. 爭議事實與理由要旨（條列說明發生經過、損害項目與法律依據）
4. 預備性退讓與和解談判底線建議（提供當事人於調解會議上可接受之底線方案、分期清償約定或拋棄其餘請求條款）
"""
        return self._call_model(prompt, temperature=0.2)

    def detect_question_domain(self, text: str) -> str:
        """
        根據輸入文字關鍵字，智能判斷法律領域
        """
        t = text.lower()
        if any(k in t for k in ["租屋", "房東", "房客", "租約", "押金", "修繕", "提前解約", "點交", "轉租", "搬家"]):
            return "🏠 不動產與房屋租賃 (租屋修繕、押金沒收、提前終止、買賣瑕疵)"
        elif any(k in t for k in ["車禍", "車輛", "撞到", "行車", "追撞", "過失傷害", "初判表", "肇責", "車損", "折舊", "理賠", "強制險"]):
            return "🚗 交通事故與侵權理賠 (車禍初判表、過失傷害、修車折舊、精神慰撫金)"
        elif any(k in t for k in ["老闆", "資遣", "非自願", "加班費", "開除", "解僱", "勞基法", "離職", "特休", "試用期", "職災", "薪水", "扣薪"]):
            return "💼 勞資爭議與勞動權益 (違法解僱、資遣費、加班費、職災補償、離職交接)"
        elif any(k in t for k in ["借錢", "本票", "借據", "利息", "欠錢", "還錢", "本票裁定", "支付命令", "債務", "擔保", "保證人"]):
            return "💰 金錢借貸與債權保障 (借據本票、本票裁定、支付命令、強制執行、消滅時效)"
        elif any(k in t for k in ["網購", "退貨", "猶豫期", "七天", "瑕疵", "消保法", "詐購", "退款", "買賣", "定型化"]):
            return "🛍️ 消費爭議與網路購物 (消保法7天猶豫期、定型化契約無效、商品瑕疵退換貨)"
        elif any(k in t for k in ["罵人", "公然侮辱", "誹謗", "名譽", "網路霸凌", "告人", "詐騙", "人頭帳戶", "警示帳戶", "告訴", "地檢署"]):
            return "🛡️ 刑法告訴與名譽保障 (妨害名譽、公然侮辱、誹謗、詐欺受害、警示帳戶申訴)"
        elif any(k in t for k in ["離婚", "外遇", "監護權", "親權", "扶養費", "遺產", "繼承", "特留分", "應繼分", "立遺囑", "分配"]):
            return "👨‍👩‍👧 婚姻家事與遺產繼承 (裁判離婚、子女親權監護、扶養費、遺產分配特留分)"
        elif any(k in t for k in ["漏水", "天花板", "樓上", "管委會", "管理費", "住戶", "規約", "噪音", "鄰居", "管線"]):
            return "🏢 公寓大廈與鄰里糾紛 (樓上漏水容忍修繕、噪音擾鄰、管委會規約爭議)"
        elif any(k in t for k in ["商標", "著作權", "侵權", "營業秘密", "競業禁止", "抄襲", "專利", "授權"]):
            return "📜 商業契約與智慧財產 (合約審閱修訂、商標著作侵權、營業秘密、競業禁止)"
        return "🌟 自動偵測 (全領域綜合剖析)"

    def _generate_offline_legal_fallback(self, prompt: str) -> str:
        """
        當網路不通或 API 額度耗盡時，提供權威詳盡的離線結構化法理分析指南
        """
        if "存證信函" in prompt:
            return """### 📮 中華民國郵局存證信函（標準格式範本）

**寄件人**：【發信人姓名/名稱】  
**詳細地址**：【發信人設籍或通訊地址】  
**聯絡電話**：【發信人聯絡電話】  

**收件人**：【相對人姓名/公司名稱/負責人】  
**詳細地址**：【相對人戶籍地或營業所地址】  

**副本收件人**：無（或載明：所在地鄉鎮市區調解委員會）

---

#### 【主旨】：
為依法催告台端於函到後【七】日內履行給付義務（或返還擔保金/賠償損害），逾期將依法提起訴訟追究民刑事責任，絕不寬貸，請查照辦理。

#### 【事實與說明】：
一、緣本人與台端間前於民國【OOO】年【OO】月【OO】日發生法律爭端（如簽訂房屋租賃契約/發生交通事故/成立承攬買賣關係）。
二、按中華民國現行法令明文保障人民權益，按民法及相關特別法規定，台端應負履行給付或損害賠償之法律義務。詎料經本人多次善意溝通與催請，台端迄今仍未依約給付，顯已違反誠信原則並損及本人法定權益甚鉅。
三、為免訟累並維法制，特以此存證信函再次正式催告台端，限於收受本函送達之日起【七】日內，出面與本人結清相關款項或完成履約。
四、倘若台端仍置若罔聞、逾期未見妥處，本人定將循法定程序檢具相關通訊截圖、匯款明細及單據，逕行向臺灣地方法院依法提起民事訴訟（或提出刑事告訴），並依法聲請假扣押或強制執行，屆時一切訴訟費用、法定利息及所衍生之損害賠償，悉由台端負全責。

**此致**  
【相對人姓名/公司名稱】 台照  

**發函人**：【發信人簽章】  
**中華民國 年 月 日**"""

        if "條文" in prompt or "哪一條" in prompt:
            return """### 🎯 一、精準核心適用法條 (Primary Statutory Provision)
依案件事實之核心特徵，核心規範條文如下：
- **實體法基礎**：民法相關規定（如債權侵權第184條、物權附合第811/812條、契約買賣瑕疵第354/359條、租賃修繕第429/430條）。
- **條文要旨**：規定權利之產生、變更、消滅或請求權行使之法定要件。

### 🧩 二、法定構成要件拆解與該當性 (Elements Analysis)
1. **主體要件**：具備權利能力與當事人適格。
2. **客觀行為**：具備客觀給付、侵權或物權處分行為。
3. **主觀歸責**：具故意或過失（若為無過失責任則不在此限）。
4. **損害與因果**：具有相當因果關係。

### ⚡ 三、法定法律效果與請求權依據 (Legal Effects & Remedies)
- 權利人依法得行使原物返還、代價補償、損害賠償或解除終止契約之法律效果。
- 消滅時效：一般民事請求權為15年，侵權行為損害賠償自知悉起2年。

### 🔍 四、相鄰與易混淆條文對比辨析 (Adjacent Confusing Provisions)
- 提醒區分債務不履行責任（如民法第227條不完全給付）與侵權責任（民法第184條）之請求權競合。

### 🏛️ 五、司法院實務權威指標字號 (Landmark Court Precedents)
- 參照最高法院確定裁判通說與大法庭裁定意旨。"""

        if "折舊" in prompt or "資遣" in prompt or "算式" in prompt or "精算" in prompt:
            return """### 📋 一、金錢請求項目定性與法理依據 (Classification of Claims)
本案金錢請求涉及損害賠償與法定給付，其法定計算基礎如下：

### 📜 二、法院認可之法定標準與計算公式 (Statutory Formula & Standards)
1. **車輛車損折舊（定率遞減法）**：
   - 自用小客車耐用年數 5 年，年折舊率為 0.369。
   - 零件每年按前一年未折舊餘額乘以 0.369 折舊，最後殘值不得低於 10%（殘值保底）。
   - 修車之「工資」費用全額賠償，依法不予折舊。
2. **勞退新制資遣費（勞工退休金條例第12條）**：
   - 每滿 1 年發給 0.5 個月平均工資，未滿 1 年以比例計算。
   - 最高發給 6 個月平均工資為限。
3. **預告期間工資（勞基法第16條）**：
   - 年資滿 3 個月未滿 1 年：10 日工資。
   - 年資滿 1 年未滿 3 年：20 日工資。
   - 年資滿 3 年以上：30 日工資。

### 🧮 三、精算步驟示範與結果總結
- 依上述法定公式代入實際數字即可得出精確得請求賠償或給付金額。"""

        # 通用六大維度離線指南
        domain = self.detect_question_domain(prompt)
        return f"""### 🎯 一、案件法律關係定性與爭端核心 (Legal Characterization)
本件諮詢案件涉及【{domain}】之法律權利義務關係。當事人間首應釐清究竟係屬民法上之契約不履行（違約責任）、侵權行為損害賠償、抑或構成刑事特別責任，並確認有無合法解除、終止或抗辯之事由。

### 📜 二、適用法律條文依據與實務見解 (Applicable Laws & Precedents)
1. **實體法請求權核心**：依民法第 153 條契約成立、第 184 條侵權行為、第 227 條不完全給付、或特定主管法規（如勞基法、消費者保護法、公寓大廈管理條例）之明文規定。
2. **法律效果判定**：需檢驗法定要件是否具備（如故意過失、損害發生、相當因果關係），並遵循民法誠實信用原則（民法第 148 條）。

### ⚖️ 三、權利主張、法律效果與抗辯評估 (Claims, Rights & Defenses)
- 權利人依法得行使返還財物、解除契約、損害賠償或履行給付之請求。
- 相對人如主張抗辯，須證明有不可歸責事由、已依債之本旨清償、或罹於法定消滅時效。

### 📋 四、關鍵證據清單與舉證責任 (Evidence & Burden of Proof)
1. 當事人間之書面協議、契約正本或電子紀錄。
2. 匯款證明、收據、發票或交付憑證。
3. 通訊軟體對話紀錄、電子郵件紀錄（需完整保存時間戳記與上下文）。
4. 第三者證人、公務機關函文或警察/公所處理紀錄。

### 🚀 五、實務救濟程序與分階段行動指南 (Action Roadmap & Remedies)
1. **階段一：蒐證與正式書面催告**：寄發郵局存證信函，載明事實、法律條文及履行期限（通常為文到 7 至 10 日）。
2. **階段二：調解委員會調解**：向各鄉鎮市區調解委員會聲請調解，調解成立經法院核定後與確定判決具同一效力。
3. **階段三：民事訴訟或非訟督促程序**：向法院聲請發支付命令（若債務人未於 20 日內異議即具執行力）或提起民事訴訟。

### ⏳ 六、法定期限、時效警示與自律提醒 (Statute of Limitations & Crucial Deadlines)
- 一般民事債權消滅時效為 **15 年**（民法第 125 條）；侵權行為損害賠償時效為 **2 年/10 年**（民法第 197 條）；短期給付（如利息、租金）為 **5 年**（民法第 126 條）。
- *免責聲明：本意見為法學實務分析原則指引，具體個案請依完整契約與事證委請專業律師辦理。*
"""
