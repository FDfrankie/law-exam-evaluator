"""
司律高階 AI 爭點查詢與權威判解・學說速查引擎 (Legal Issue & Precedent Query Engine)
整合本機 824+ 份權威判解庫 (最高法院大法庭裁定全集、憲法法庭判決與大法官解釋、最高法院精選裁判)
與 Gemini 2.0 Flash 深度法學推論模型。
功能：
1. 精準引出相關實體法與程序法法條（條號、構成要件與法律效果）
2. 列出核心法律爭點（爭執核心與規範疑義）
3. 嚴格依權威位階列出司法裁判（憲判字/釋字 > 大法庭裁定 > 最高法院精選裁判/判例）
4. 全面深入對照通說與學者有力說（肯否兩說）
"""
import os
import sys
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from google import genai
    from google.genai import types as genai_types
    USE_MODERN_GENAI = True
except ImportError:
    try:
        import google.generativeai as legacy_genai
    except ImportError:
        legacy_genai = None
    USE_MODERN_GENAI = False

from config import get_gemini_api_key, DEFAULT_GEMINI_MODEL, RAW_DATA_DIR, DATA_DIR, get_gemini_models_to_try

CATALOG_PATHS = [
    Path(RAW_DATA_DIR) / "precedents_catalog.json",
    Path(__file__).resolve().parent / "data" / "raw_exams" / "precedents_catalog.json",
    Path(DATA_DIR) / "raw_exams" / "precedents_catalog.json"
]

_CACHED_CATALOG: Optional[List[Dict[str, Any]]] = None

def get_precedents_catalog() -> List[Dict[str, Any]]:
    """載入權威裁判目錄庫 (含最高法院民刑大法庭、憲法法庭與大法官解釋)"""
    global _CACHED_CATALOG
    if _CACHED_CATALOG is not None:
        return _CACHED_CATALOG

    catalog_data: List[Dict[str, Any]] = []
    for p in CATALOG_PATHS:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list) and len(data) > 0:
                    catalog_data = data
                    break
            except Exception:
                pass

    # 合併內建指標法學判解全文庫 (BUILTIN_LANDMARK_DOCS)
    try:
        from legal_summarizer_engine import BUILTIN_LANDMARK_DOCS
        existing_cids = {c.get("case_id", "").replace(" ", "") for c in catalog_data}
        for b in BUILTIN_LANDMARK_DOCS:
            title = b.get('title', '')
            text = b.get('text', '')
            cid_match = re.search(r'([^\n（(]+)', title)
            cid = cid_match.group(1).strip() if cid_match else title
            if cid.replace(" ", "") not in existing_cids:
                court = "最高行政法院" if "最高行政" in title else (
                    "憲法法庭" if "憲法法庭" in title or "憲判" in title else (
                        "智慧財產及商業法院" if "智慧財產" in title else (
                            "臺灣高等法院" if "高等法院" in title else "最高法院"
                        )
                    )
                )
                level = "終審法律審" if ("最高" in court or "憲法" in court) else "高等法院事實審"
                subject = "行政法" if ("行政" in court or "函釋" in b.get("doc_type", "")) else (
                    "民法與民事訴訟法" if "民" in title or "民事" in text else "刑法與刑事訴訟法"
                )
                issue_m = re.search(r'【(?:爭點|裁判核心法律爭點|案件核心法律爭點)[^】]*】：?\s*([\s\S]*?)(?=【|$)', text)
                holding_m = re.search(r'【(?:判決主文|主文|裁判核心理由|最高行政法院判決理由要旨|理由要旨|核心理由|要旨)[^】]*】：?\s*([\s\S]*?)(?=【|$)', text)
                hint_m = re.search(r'【(?:司律二試[^】]*|考點提示)[^】]*】：?\s*([\s\S]*?)(?=【|$)', text)
                catalog_data.append({
                    'case_id': cid,
                    'court': court,
                    'level': level,
                    'subject': subject,
                    'sub_category': title,
                    'date': '111-12-22' if '110' in cid and '15' in cid else '',
                    'title': title,
                    'laws_cited': re.findall(r'(?:憲法|地方制度法|民法|刑法|民事訴訟法|刑事訴訟法|行政訴訟法)第\d+(?:條之\d+|條)?', text),
                    'issue': issue_m.group(1).strip() if issue_m else title,
                    'holding': holding_m.group(1).strip() if holding_m else text[:300],
                    'scholarly_views': '',
                    'exam_application_hint': hint_m.group(1).strip() if hint_m else ''
                })
                existing_cids.add(cid.replace(" ", ""))
    except Exception:
        pass

    _CACHED_CATALOG = catalog_data
    return _CACHED_CATALOG

COMMON_CASE_WORDS = [
    "全部字別 (不限)",
    "憲判", "憲裁", "台上大", "台抗大", "台聲大", "台上", "台抗", "台再", "台聲", "台非",
    "重上", "上易", "保險上", "勞上", "金上", "海商上", "家上", "加上",
    "民著上", "民專上", "行專上", "行商上", "智民上",
    "上更（一）", "上更（二）", "重上更（一）", "重上更（二）", "重上更一", "重上更二",
    "訴", "重訴", "金訴", "上訴", "上重訴", "金上訴", "智訴", "矚訴",
    "交訴", "交易", "選訴", "易", "簡", "簡上", "抗", "自", "判例", "決議", "座談會"
]

EXTENDED_JUDICIAL_AUTHORITIES = [
    # --- 一、最高法院／最高行政法院 原判例（依法院組織法第57條之1具裁判全文者效力同最高院裁判） ---
    {
        "case_id": "最高法院 40 年台上字第 86 號民事判例",
        "court": "最高法院",
        "level": "最高法院原判例（民事實體標竿）",
        "subject": "民法與民事訴訟法",
        "sub_category": "消滅時效與權利濫用",
        "date": "1951/02/16",
        "title": "不動產真正所有人之登記名義回復與權利行使誠信原則案（40年台上字第86號原判例）",
        "laws_cited": ["民法第148條", "民法第767條", "民法第758條"],
        "issue": "債務人或出賣人久未辦理移轉登記或遲延行使權利，應否受民法第148條誠實信用原則與權利濫用禁止之拘束？",
        "holding": "權利之行使，不得違反公共利益，或以損害他人為主要目的。行使權利，履行義務，應依誠實及信用方法。若當事人行使物上請求權或債權請求權違反誠信原則者，法院得認其為權利濫用而不予保護。",
        "scholarly_views": "【實務與通說】肯認民法第148條誠信原則為全體私法之帝王條款，並衍生『權利失效理論』。",
        "exam_application_hint": "二試考題若出現權利人長期沉默不使權利致相對人產生正當信賴，務必引述民法第148條及最高法院40年台上字第86號等判例法理檢討權利失效。"
    },
    {
        "case_id": "最高法院 30 年上字第 482 號民事判例",
        "court": "最高法院",
        "level": "最高法院原判例（民事實體標竿）",
        "subject": "民法與民事訴訟法",
        "sub_category": "無權處分與善意受讓",
        "date": "1941/03/12",
        "title": "動產無權處分與民法第801條、第948條善意受讓之要件案（30年上字第482號原判例）",
        "laws_cited": ["民法第118條", "民法第801條", "民法第948條"],
        "issue": "動產善意受讓之成立，除受讓人為善意且無重大過失外，是否以實際受占有之移轉（交付）為必要？",
        "holding": "民法第801條及第948條規定動產之善意受讓，係以動產占有之移轉為要件；倘無占有之移轉或僅依占有改定而未現實交付者，受讓人尚不得主張即時取得動產所有權。",
        "scholarly_views": "【實務與王澤鑑教授通說】占有改定（民法第761條第2項）欠缺外部公示外觀，原則上須至受讓人受現實交付時始生善意受讓效力。",
        "exam_application_hint": "考無權處分＋占有改定時，應引述民法第948條第2項與30年上字第482號判例意旨。"
    },
    {
        "case_id": "最高法院 65 年台上字第 2440 號民事判例",
        "court": "最高法院",
        "level": "最高法院原判例（民事實體標竿）",
        "subject": "民法與民事訴訟法",
        "sub_category": "侵權行為與過失相抵",
        "date": "1976/10/15",
        "title": "被害人使用人或代理人之與有過失類推適用民法第217條第3項案（65年台上字第2440號原判例）",
        "laws_cited": ["民法第184條", "民法第217條第1項", "民法第217條第3項"],
        "issue": "駕駛人搭載被害人發生車禍事故，被害人對於該駕駛人（使用人）之過失是否應承擔過失相抵責任？",
        "holding": "民法第217條第3項規定被害人之代理人或使用人與有過失者準用過失相抵。旨在謀求加害人與被害人間之公平分擔，被害人搭乘他人駕駛之車輛，對該駕駛人具有選任監督或利益共同關係時，應類推適用與有過失減輕加害人賠償金額。",
        "scholarly_views": "【實務與陳聰富教授】區分『無償順風車』與『為被害人服勞務之使用人』，惟實務多肯定擴大適用過失相抵。",
        "exam_application_hint": "車禍侵權題型必考：討論甲車駕駛與乙車駕駛過失撞傷乘客丙時，丙是否須就甲之過失負與有過失責任。"
    },
    {
        "case_id": "最高法院 29 年上字第 1061 號民事判例",
        "court": "最高法院",
        "level": "最高法院原判例（物權與不當得利標竿）",
        "subject": "民法與民事訴訟法",
        "sub_category": "無權占有與不當得利",
        "date": "1940/06/20",
        "title": "無權占有他人土地或房屋受有相當於租金之利益案（29年上字第1061號原判例）",
        "laws_cited": ["民法第179條", "民法第767條", "民法第181條"],
        "issue": "無權占有他人之不動產，所有權人得否不待證明自己受有無法出租之實際損害，直接依民法第179條請求返還相當於租金之不當得利？",
        "holding": "無法律上之原因而占有他人之土地或房屋，依社會通常觀念，占有人即受有相當於租金之利益，並致所有權人受有相當於租金之損害，所有權人自得依不當得利之法則請求返還。",
        "scholarly_views": "【王澤鑑教授權益歸屬說】無權使用他人之物乃侵害所有權之排他使用收益權能（違反權益歸屬），所受利益即為使用本身，客觀價額以相當於租金計算，無庸檢驗所有權人原有無出租計畫。",
        "exam_application_hint": "二試考民法第767條物上返還時，必定成對搭配民法第179條＋本號判例（或權益歸屬說）請求相當於租金之不當得利！"
    },
    {
        "case_id": "最高法院 76 年台上字第 4986 號刑事判例",
        "court": "最高法院",
        "level": "最高法院原判例（刑事證據法則標竿）",
        "subject": "刑法與刑事訴訟法",
        "sub_category": "相當因果關係與證據法則",
        "date": "1987/08/21",
        "title": "刑法結果犯之『相當因果關係』判斷標準案（76年台上字第4986號原判例）",
        "laws_cited": ["刑法第15條", "刑法第271條", "刑法第276條", "刑事訴訟法第154條"],
        "issue": "刑法上行為與結果間之因果關係應採何種判斷基準？",
        "holding": "刑法上之因果關係，以『相當因果關係』為準：即依經驗法則，綜合行為當時所存在之一切事實，為客觀之事後審查，認為在一般情形下，有此環境、有此行為之同一條件，均可發生同一之結果者，則該條件即為發生結果之相當條件，行為與結果即有相當之因果關係。",
        "scholarly_views": "【實務傳統見解】採76年台上字第4986號判例之相當因果關係說；【學說主流（林鈺雄、許恒達、王皇玉教授）】採『條件理論＋客觀歸責理論』（製造法所不容許之風險、風險實現、構成要件效力範圍），近年最高法院裁判亦大量融合客觀歸責理論。",
        "exam_application_hint": "刑法總則因果關係開標必備：先並列【實務76台上4986相當因果關係說】與【學說客觀歸責理論】，再以客觀歸責三階層涵攝！"
    },
    {
        "case_id": "最高法院 28 年上字第 3218 號刑事判例",
        "court": "最高法院",
        "level": "最高法院原判例（刑事共犯標竿）",
        "subject": "刑法與刑事訴訟法",
        "sub_category": "共同正犯之要件",
        "date": "1939/09/15",
        "title": "共同正犯之犯意聯絡與行為分擔及一部行為全部責任原則案（28年上字第3218號原判例）",
        "laws_cited": ["刑法第28條"],
        "issue": "共同正犯中之一人僅參與部分構成要件行為，是否仍應對全部犯罪結果負共同正犯之責？",
        "holding": "共同正犯之所以應對其他共同正犯所實施之行為負其全部責任者，以就其行為有犯意之聯絡與行為之分擔為要件；在合同意思範圍以內，各自分擔犯罪行為之一部，相互利用他人之行為，以達其犯罪之目的者，即應對於全部所發生之結果，共同負責。",
        "scholarly_views": "【實務與學說】結合釋字第109號解釋（共謀共同正犯）與犯罪支配理論（功能性犯罪支配）。",
        "exam_application_hint": "刑法共同正犯必引大前提：刑法第28條、釋字第109號及28年上字第3218號判例之『一部行為全部責任原則』。"
    },
    {
        "case_id": "最高行政法院 75 年判字第 309 號判例",
        "court": "最高行政法院",
        "level": "最高行政法院原判例（行政處分標竿）",
        "subject": "行政法",
        "sub_category": "行政處分與觀念通知之區辨",
        "date": "1986/03/07",
        "title": "行政機關單純事實敘述或理由說明（觀念通知）非屬行政處分案（75年判字第309號原判例）",
        "laws_cited": ["行政程序法第92條", "訴願法第1條", "行政訴訟法第4條"],
        "issue": "行政機關就法令疑義之函覆、單純事實之敘述或重複先前處分之通知，人民得否對之提起撤銷訴願及撤銷訴訟？",
        "holding": "官署所為單純的事實敘述或理由說明，並非對人民之請求有所准駁，既不因該項敘述或說明而生法律上之效果，非訴願法上之行政處分，人民對之提起訴願，自非法之所許。",
        "scholarly_views": "【實務與行政法通說】區辨『行政處分（具法效性／規制性）』與『觀念通知（認知表示／事實行為）』之最核心實務判準。",
        "exam_application_hint": "行政法定性第一題必考：先引行政程序法第92條第1項六大要素，再引最高行政法院75年判字第309號判例檢驗是否具『直接對外發生法律效果之規制性』！"
    },

    # --- 二、最高法院民刑庭會議決議 ／ 最高行政法院庭長法官聯席會議決議 ---
    {
        "case_id": "最高法院 77 年度第 7 次民事庭會議決議",
        "court": "最高法院民事庭會議",
        "level": "最高法院民庭決議（債編天王級決議）",
        "subject": "民法與民事訴訟法",
        "sub_category": "物之瑕疵擔保與不完全給付競合",
        "date": "1988/04/19",
        "title": "出賣人交付之標的物有瑕疵時，買受人物之瑕疵擔保請求權與不完全給付損害賠償請求權之競合案",
        "laws_cited": ["民法第354條", "民法第359條", "民法第360條", "民法第227條", "民法第365條"],
        "issue": "買賣標的物於危險移轉時已有瑕疵（或訂約時即有瑕疵），買受人除得主張民法第359條、第360條物之瑕疵擔保責任外，得否同時主張民法第227條不完全給付之損害賠償？",
        "holding": "出賣人就其交付之買賣標的物有應負擔保責任之瑕疵，而其瑕疵係於契約成立後始發生，且因可歸責於出賣人之事由所致者，則出賣人除負物之瑕疵擔保責任外，同時構成不完全給付之債務不履行責任。買受人如主張不完全給付，須出賣人有可歸責事由；且其解除契約或減少價金之權利行使期間，仍受民法第365條短期時效/除斥期間之規範。",
        "scholarly_views": "【實務決議見解】肯定自由競合說（惟不完全給付須具可歸責性）；【學者見解（王澤鑑、陳自強教授）】探討瑕疵結果損害（加害給付）與瑕疵給付本身損害之分際，及民法第365條6個月除斥期間是否及於第227條請求權。",
        "exam_application_hint": "民法買賣瑕疵必考決議！務必背誦『最高法院77年度第7次民事庭會議決議』，分別檢驗：(1)物之瑕疵擔保（無過失責任，受356檢查通知義務及365期間限制）；(2)第227條不完全給付（過失責任，分瑕疵給付與加害給付）。"
    },
    {
        "case_id": "最高法院 95 年度第 16 次民事庭會議決議",
        "court": "最高法院民事庭會議",
        "level": "最高法院民庭決議（債編核心決議）",
        "subject": "民法與民事訴訟法",
        "sub_category": "違約定金與違約金酌減",
        "date": "2006/11/14",
        "title": "定金約定沒收（違約定金）過高時，法院得否類推適用民法第252條予以酌減案",
        "laws_cited": ["民法第248條", "民法第249條", "民法第252條"],
        "issue": "當事人依民法第249條第2款沒收定金或加倍返還定金，若該定金數額顯然過高時，法院得否類推適用民法第252條違約金酌減之規定予以核減？",
        "holding": "除當事人另有約定定金具有違約金之性質（違約定金）外，法定之證約定金或立約定金因可歸責於付定金當事人之事由致不能履行時，受定金人依民法第249條第2款不得請求返還，乃法定效果，原則上無民法第252條酌減之適用；惟倘實質上屬於『違約定金』且金額過高顯失公平者，得類推適用民法第252條酌減。",
        "scholarly_views": "【實務與學說】區辨法定沒收定金與意定違約定金，若定金高達總價款相當比例且具預定賠償性質，應容許類推第252條酌減以維衡平。",
        "exam_application_hint": "考不動產買賣沒收高額定金時，務必引述95年第16次民庭決議，先定性是否屬『違約定金』，再論類推適用民法第252條。"
    },
    {
        "case_id": "最高法院 106 年度第 3 次民事庭會議決議",
        "court": "最高法院民事庭會議",
        "level": "最高法院民庭決議（物權核心決議）",
        "subject": "民法與民事訴訟法",
        "sub_category": "已登記不動產與消滅時效",
        "date": "2017/02/21",
        "title": "借名登記終止後之返還請求權性質（債權請求權 vs 物上請求權）及消滅時效案",
        "laws_cited": ["民法第125條", "民法第179條", "民法第541條", "民法第767條", "釋字第107號", "釋字第164號"],
        "issue": "不動產借名登記契約終止後，借名人請求出名人移轉返還不動產所有權登記之請求權，其性質究屬債權請求權或物上請求權？是否適用民法第125條15年消滅時效？",
        "holding": "不動產借名登記契約終止後，借名人依類推適用民法第541條第2項或第179條不當得利規定，請求出名人返還（移轉登記）不動產之權利，性質上屬於『債權請求權』，並非民法第767條之物上請求權，故無司法院釋字第107號及第164號解釋之適用，仍應適用民法第125條15年消滅時效之規定。",
        "scholarly_views": "【實務一貫見解】借名人未登記為所有人，無從行使第767條物上請求權；終止後之返還請求權屬債權請求權，適用15年時效。",
        "exam_application_hint": "與108台上大1719裁定並列借名登記雙核心：對外處分引108台上大1719（有權處分）；內部終止返還時效引106年第3次民庭決議（債權請求權，適用15年消滅時效）！"
    },
    {
        "case_id": "最高法院 96 年度第 8 次民事庭會議決議",
        "court": "最高法院民事庭會議",
        "level": "最高法院民庭決議（身分繼承標竿）",
        "subject": "民法與民事訴訟法",
        "sub_category": "剩餘財產分配與特留分",
        "date": "2007/11/06",
        "title": "夫妻剩餘財產差額分配請求權於計算遺產及特留分時之扣除順序案",
        "laws_cited": ["民法第1030條之1", "民法第1153條", "民法第1223條", "民法第1224條"],
        "issue": "被繼承人死亡致法定財產制關係消滅時，生存配偶依民法第1030條之1主張之剩餘財產差額分配請求權，在遺產繼承與特留分計算上應如何處理？",
        "holding": "生存配偶之剩餘財產差額分配請求權，性質上屬被繼承人遺產之『婚姻法上債務（外部債務）』，應先自被繼承人遺產總額中扣除該差額分配額後，就剩餘之淨遺產再依民法第1144條計算各繼承人之應繼分及依第1224條計算特留分。",
        "scholarly_views": "【身分法通說（林秀雄、戴瑀如教授）】完全肯認先分配夫妻剩餘財產（扣除債務），再就餘額進行遺產繼承分割。",
        "exam_application_hint": "身分法計算題黃金公式：第一步算民法第1030條之1剩餘財產差額；第二步從死亡配偶遺產先扣除該差額；第三步才按應繼分與特留分比例分配！"
    },
    {
        "case_id": "最高法院 94 年度第 2 次刑事庭會議決議",
        "court": "最高法院刑事庭會議",
        "level": "最高法院刑庭決議（刑訴證據標竿）",
        "subject": "刑法與刑事訴訟法",
        "sub_category": "傳聞例外與證據能力",
        "date": "2005/02/01",
        "title": "刑事訴訟法第159條之5傳聞證據擬制同意之適用要件與防禦權保障案",
        "laws_cited": ["刑事訴訟法第159條第1項", "刑事訴訟法第159條之5"],
        "issue": "被告及辯護人於審判期日前或審判中對傳聞證據未於言詞辯論終結前聲明異議，法院適用刑事訴訟法第159條之5第2項擬制同意時，應如何審酌『適當性』要件？",
        "holding": "刑事訴訟法第159條之5之立法意旨，在於確認當事人對於傳聞證據有處分權，惟法院仍應審查該證據作成時之情況，是否無違法取證、證明力非顯然過低等情事，認為適當者，始得賦予證據能力。",
        "scholarly_views": "【實務與林鈺雄教授】強調第159條之5『雙重要件』：(1)當事人明示或擬制同意＋(2)法院審酌作成情況認為適當（若係違法強制取證則不得因同意而治癒）。",
        "exam_application_hint": "刑訴傳聞法則結尾必寫第159條之5：記得檢驗『同意』＋『法院審酌作成情況適當』兩大要件。"
    },
    {
        "case_id": "最高行政法院 101 年 6 月份第 1 次庭長法官聯席會議決議",
        "court": "最高行政法院庭長法官聯席會議",
        "level": "最高行政法院決議（公法雙階理論標竿）",
        "subject": "行政法",
        "sub_category": "政府採購與公法請求權時效",
        "date": "2012/06/12",
        "title": "政府採購法第31條第2項追繳押標金之行政處分定性與行政程序法第131條公法上請求權消滅時效起算案",
        "laws_cited": ["政府採購法第31條第2項", "行政程序法第92條", "行政程序法第131條第1項"],
        "issue": "招標機關依政府採購法第31條第2項向廠商追繳押標金，其法律性質為何？公法上請求權5年消滅時效應自何時起算？",
        "holding": "招標機關依政府採購法第31條第2項規定追繳廠商押標金之行為，屬公法事件，其所為追繳之通知具有行政處分之性質；其5年公法上請求權消滅時效，應自可合理期待機關得為追繳時起算。",
        "scholarly_views": "【公法雙階理論】政府採購於決標前（招標、審標、決標、追繳押標金、不良廠商停權）屬公法關係（行政處分）；決標後履約爭議、沒收履約保證金則屬私法契約關係（民事訴訟）。",
        "exam_application_hint": "行政法政府採購題型必背對照：追繳『押標金』＝行政處分（101年6月第1次決議）；沒收『履約保證金』＝私法爭議（民事法院管轄）！"
    },

    # --- 三、臺灣高等法院暨所屬法院法律座談會（民、刑、家事、執行類指標提案） ---
    {
        "case_id": "臺灣高等法院暨所屬法院 108 年法律座談會民事類提案第 5 號",
        "court": "臺灣高等法院暨所屬法院法律座談會",
        "level": "高院法律座談會（民事實務重要研討）",
        "subject": "民法與民事訴訟法",
        "sub_category": "借名登記內部求償與不當得利",
        "date": "2019/11/20",
        "title": "借名登記出名人擅自處分不動產後，借名人對出名人主張債務不履行、侵權行為與不當得利之請求權基礎與計算標準案",
        "laws_cited": ["民法第179條", "民法第184條第1項後段", "民法第226條", "民法第544條"],
        "issue": "出名人未經借名人同意將借名不動產出賣予第三人（依108台上大1719屬有權處分），借名人對出名人得依何種請求權基礎求償？得否依民法第179條請求返還出賣所得價金？",
        "holding": "【研討結果採肯定說】出名人違反借名登記內部約定擅自處分標的物，對借名人構成類推適用民法第544條委任契約債務不履行（第226條給付不能）損害賠償、第184條第1項後段背俗侵權行為，借名人亦得依第179條不當得利或第177條第2項不法管理請求出名人返還所獲買賣價金利益。",
        "scholarly_views": "【實務與王澤鑑教授】108台上大1719解決了『外部對第三人有權處分』，而高院座談會與學說則確立『內部對出名人之多元救濟途徑（544/226債務不履行、184I後段背俗侵權、177II不法管理、179不當得利）』。",
        "exam_application_hint": "二試借名登記題通常有兩小題：第(一)小題問丙是否取得所有權（引108台上大1719有權處分）；第(二)小題問甲對乙如何求償（引本則座談會與民法544、226、184I後段、177II、179）！"
    },
    {
        "case_id": "臺灣高等法院暨所屬法院 110 年法律座談會民事類提案第 8 號",
        "court": "臺灣高等法院暨所屬法院法律座談會",
        "level": "高院法律座談會（侵權損害賠償實務）",
        "subject": "民法與民事訴訟法",
        "sub_category": "交易性貶值損失與回復原狀",
        "date": "2021/11/17",
        "title": "車輛或房屋因侵權行為受損經修復後，被害人得否另依民法第196條請求『交易性貶值（事故車價值減損）』賠償案",
        "laws_cited": ["民法第184條", "民法第196條", "民法第213條", "民法第215條"],
        "issue": "物因侵權行為毀損，被害人除請求物理修復費用（零件折舊後金額＋工資）外，就修復後在交易市場上仍存在之『交易性價值貶損（如事故車折價）』，得否依民法第196條或第215條請求金錢賠償？",
        "holding": "【研討結果採肯定說】物之毀損雖經技術性修復，惟依社會交易觀念（如重大事故車、凶宅或結構受損建物），其市場交易價值較諸未受損前仍有顯著減損者，該『交易性貶值』亦屬民法第196條或第215條價值利益賠償之範圍，被害人經舉證或鑑定證明後得請求賠償。",
        "scholarly_views": "【實務與陳聰富教授】肯認物理上回復原狀若無法填補交易價值減損，應准許請求交易性貶值，以貫徹完全賠償原則。",
        "exam_application_hint": "侵權損賠進階考點：除了算零件折舊與工資外，別忘了加上『交易性貶值損失（高院110年民事座談會提案8）』！"
    },
    {
        "case_id": "臺灣高等法院暨所屬法院 111 年法律座談會民事執行類提案第 3 號",
        "court": "臺灣高等法院暨所屬法院法律座談會",
        "level": "高院法律座談會（強制執行與抵押權實務）",
        "subject": "民法與民事訴訟法",
        "sub_category": "抵押權拍賣除去租賃權",
        "date": "2022/11/16",
        "title": "抵押權設定後成立之租賃關係影響抵押權實現時，執行法院依民法第866條第2項除去租賃權之程序與要件案",
        "laws_cited": ["民法第866條第1項", "民法第866條第2項", "民法第425條", "強制執行法第98條"],
        "issue": "不動產所有人於設定抵押權後，將不動產出租予第三人，於拍賣程序中無人應買或出價不足清償抵押債權時，執行法院依民法第866條第2項除去租賃權之審查基準為何？",
        "holding": "不動產所有人設定抵押權後於同一不動產上成立租賃關係，若因該租賃權存在致第一次拍賣無人應買，或應買人所出最高價不足清償優先抵押債權時，即足認『於抵押權有影響』，執行法院得依聲請或依職權發除租命令，於除去後以無租賃狀態點交予拍定人。",
        "scholarly_views": "【物權與強執法實務】調和民法第425條買賣不破租賃與第866條抵押權優先受償價值保護。",
        "exam_application_hint": "民法物權與強執跨科考點：先設定抵押權 ➔ 後出租交付（425）➔ 拍賣影響抵押權時，引民法第866條第2項＋高院執行座談會除去租賃！"
    },
    {
        "case_id": "臺灣高等法院暨所屬法院 110 年法律座談會刑事類提案第 6 號",
        "court": "臺灣高等法院暨所屬法院法律座談會",
        "level": "高院法律座談會（刑事詐欺與洗錢實務）",
        "subject": "刑法與刑事訴訟法",
        "sub_category": "加重詐欺與一般洗錢罪",
        "date": "2021/11/17",
        "title": "詐欺集團車手提領贓款並交予上手之行為，構成加重詐欺罪與洗錢防制法一般洗錢罪之競合關係案",
        "laws_cited": ["刑法第339條之4", "洗錢防制法第2條", "洗錢防制法第19條", "刑法第55條"],
        "issue": "詐欺集團成員（車手）持人頭帳戶提款卡提領被害人匯入之款項並轉交上手，製造金流斷點以隱匿犯罪所得去向，應如何論處加重詐欺罪與洗錢罪之罪數與競合？",
        "holding": "【研討結果與最高法院大法庭見解一致】車手提領贓款並交付上手，已產生切斷資金追查軌跡、掩飾或隱匿特定犯罪所得去向之效果，同時該當刑法第339條之4第1項第2款三人以上共同詐欺取財罪及洗錢防制法一般洗錢罪，二罪間具行為局部重合，依刑法第55條想像競合犯從一重處斷。",
        "scholarly_views": "【實務定錨見解】結合最高法院108年度台上大字第3101號刑事大法庭裁定與高院刑事座談會，明確界定車手與提供帳戶者之洗錢罪責。",
        "exam_application_hint": "刑法分則與特別刑法必考：車手提款交上手＝加重詐欺＋一般洗錢罪（想像競合）；單純提供人頭帳戶未參與提領＝幫助詐欺＋幫助洗錢（參108台上大3101）。"
    },
    {
        "case_id": "臺灣高等法院暨所屬法院 112 年法律座談會刑事類提案第 4 號",
        "court": "臺灣高等法院暨所屬法院法律座談會",
        "level": "高院法律座談會（科技偵查與刑訴實務）",
        "subject": "刑法與刑事訴訟法",
        "sub_category": "科技偵查與證據排除",
        "date": "2023/11/15",
        "title": "偵查機關實施科技偵查定位或非附隨於合法拘捕之搜索取證，其證據能力依刑事訴訟法第158條之4權衡審查案",
        "laws_cited": ["刑事訴訟法第158條之4", "刑事訴訟法第131條之1", "憲法第22條"],
        "issue": "司法警察於欠缺急迫情狀或未獲真摯自願同意下所取得之物證，法院依刑事訴訟法第158條之4審酌人權保障與公共利益之均衡維護時，應考量哪些具體基準？",
        "holding": "法院依刑事訴訟法第158條之4權衡時，應綜合審酌：(1)違背法定程序之情節輕重；(2)違背法定程序時之主觀意圖（是否出於惡意規避令狀原則）；(3)侵害犯罪嫌疑人或第三人基本權之種類及輕重；(4)犯罪所生之危險或實害；(5)禁止使用證據對於預防將來違法取證之效果；(6)偵查人員如依法定程序有無發現該證據之必然性。",
        "scholarly_views": "【實務與林鈺雄、王兆鵬教授】融合最高法院93年台上字第664號判例之八大權衡要素與111年憲判字第16號正當法律程序要求。",
        "exam_application_hint": "刑訴違法取證收尾必背：引刑事訴訟法第158條之4＋最高法院93台上664號判例及高院112年刑事座談會之權衡要素。"
    }
]

COURTS_TAXONOMY = {
    "全部法院 (全體司法體系)": [],
    "📜 最高法院/最高行 原判例專區": ["原判例", "判例"],
    "⚖️ 最高法院/最高行 庭長法官聯席會議決議": ["民事庭會議", "刑事庭會議", "庭長法官聯席會議", "決議"],
    "📋 臺灣高等法院暨所屬法院 法律座談會": ["法律座談會", "座談會"],
    "🏛️ 憲法法院系統": ["憲法法庭", "司法院大法官", "司法院公報"],
    "🏛️ 最高法院 (終審法院)": ["最高法院", "最高法院民事庭", "最高法院刑事庭", "最高法院民事大法庭", "最高法院刑事大法庭"],
    "🏛️ 最高行政法院": ["最高行政法院", "最高行政法院大法庭"],
    "🏛️ 高等法院及各分院 (二審事實審)": ["臺灣高等法院", "臺灣高等法院臺中分院", "臺灣高等法院臺南分院", "臺灣高等法院高雄分院", "臺灣高等法院花蓮分院", "福建高等法院金門分院"],
    "🏛️ 高等行政法院 (公法事實審)": ["臺北高等行政法院", "臺中高等行政法院", "高雄高等行政法院"],
    "🏛️ 智慧財產及商業法院": ["智慧財產及商業法院", "智慧財產法院"],
    "🏛️ 懲戒法院 (公務員暨司法人員)": ["懲戒法院", "公務員懲戒委員會"],
    "🏛️ 地方法院 (一審事實審)": [
        "臺灣臺北地方法院", "臺灣新北地方法院", "臺灣士林地方法院", "臺灣桃園地方法院",
        "臺灣新竹地方法院", "臺灣苗栗地方法院", "臺灣臺中地方法院", "臺灣彰化地方法院",
        "臺灣南投地方法院", "臺灣雲林地方法院", "臺灣嘉義地方法院", "臺灣臺南地方法院",
        "臺灣高雄地方法院", "臺灣橋頭地方法院", "臺灣屏東地方法院", "臺灣臺東地方法院",
        "臺灣花蓮地方法院", "臺灣宜蘭地方法院", "臺灣基隆地方法院", "臺灣澎湖地方法院",
        "福建金門地方法院", "福建連江地方法院"
    ]
}

JUDICIAL_TIME_RANGES = [
    "全部時間 (不限年份)",
    "近 1 年 (最新考點・民國 113~115 年)",
    "近 3 年 (實務定錨・民國 111~115 年)",
    "近 5 年 (大法庭黃金期・民國 109~115 年)",
    "近 10 年 (司法革新期・民國 104~115 年)",
    "近 30 年 (現代憲法裁判大典・民國 84~115 年)"
]

def extract_case_roc_year(item: Dict[str, Any]) -> int:
    """提取裁判或解釋之民國年度 (ROC Year)，供時間軸過濾使用"""
    cid = item.get("case_id", "")
    dt = item.get("date", "")
    # 1. 案號直接匹配 (例: 108年度, 111年, 106亡)
    m = re.search(r'(\d{2,3})\s*(?:年度|年)', cid)
    if m:
        y = int(m.group(1))
        if 10 <= y <= 130:
            return y
    # 2. 日期欄位解析 (例: 2020/02/21 或 108.02.21)
    if dt:
        ym = re.search(r'(\d{4})[/-]', dt)
        if ym:
            return int(ym.group(1)) - 1911
        roc_m = re.search(r'(\d{2,3})[/-]', dt)
        if roc_m:
            y = int(roc_m.group(1))
            if 10 <= y <= 130:
                return y
    # 3. 司法院大法官解釋序列 (釋字第 1~813 號)
    if "釋字" in cid:
        num_m = re.search(r'釋字第?\s*(\d+)\s*號', cid)
        if num_m:
            no = int(num_m.group(1))
            if no >= 800:
                return 110
            elif no >= 750:
                return 106
            elif no >= 700:
                return 101
            elif no >= 600:
                return 95
            elif no >= 500:
                return 89
            else:
                return 70
    # 4. 開頭數字容錯
    num_lead = re.match(r'^\D*(\d{2,3})\b', cid)
    if num_lead:
        y = int(num_lead.group(1))
        if 20 <= y <= 125:
            return y
    return 100

PRESET_JUDGEMENT_HISTORIES: Dict[str, Dict[str, Any]] = {
    "108台上大1719": {
        "case_id": "最高法院 108 年度台上大字第 1719 號民事大法庭裁定",
        "title": "不動產借名登記之出名人未經同意處分標的物究屬有權處分或無權處分案",
        "topic": "借名登記出名人擅自處分不動產之效力（有權處分說定錨）",
        "timeline_stages": [
            {
                "stage": "一審事實審",
                "court": "臺灣臺北地方法院",
                "case_no": "105年度重訴字第120號民事判決",
                "ruling": "原告勝訴（借名人勝訴）",
                "holding_summary": "一審認為借名登記僅由出名人代為登記，出名人內部無實質處分權，未經同意擅自出賣並移轉所有權與第三人，屬無權處分，移轉登記應予塗銷。"
            },
            {
                "stage": "二審上訴審（見解逆轉）",
                "court": "臺灣高等法院",
                "case_no": "105年度重上字第850號民事判決",
                "ruling": "改判原告敗訴（出名人與買受人勝訴）",
                "holding_summary": "高等法院見解重大逆轉！基於民法不動產物權登記之公示原則與公信力，出名人既為登記名義人，在法律上即為所有權人，處分屬有權處分，內部借名關係不得對抗第三人。"
            },
            {
                "stage": "三審法律審提案",
                "court": "最高法院民事第三庭",
                "case_no": "106年度台上字第2253號民事事件",
                "ruling": "向大法庭提案統一法律見解",
                "holding_summary": "第三審合議庭評議時發現，最高法院以往見解發生歧異：98年度台上字第76號等判例認屬無權處分，但亦有庭期認屬有權處分，遂裁定提案交付大法庭統一定錨。"
            },
            {
                "stage": "大法庭終局定錨裁定",
                "court": "最高法院民事大法庭",
                "case_no": "108年度台上大字第1719號裁定",
                "ruling": "終局定錨：採「有權處分說」",
                "holding_summary": "不動產借名登記出名人未經借名人同意擅自處分者，為有權處分！買受人縱為惡意（明知借名登記存在），亦取得標的物所有權。借名人僅得向出名人請求債務不履行或侵權損害賠償。"
            },
            {
                "stage": "受提案庭終局裁判",
                "court": "最高法院民事第三庭",
                "case_no": "106年度台上字第2253號民事判決",
                "ruling": "上訴駁回確定",
                "holding_summary": "受提案庭嚴格受大法庭裁定拘束，依有權處分說判決駁回借名人之上訴，全案判決確定。"
            }
        ],
        "distinguishing_insight": "事實審與法律審交鋒焦點：借名關係為『內部債權契約』，不得突破物權公示外觀！二試作答時若僅寫無權處分即屬舊實務，必須精準點出大法庭有權處分說之定錨轉折。",
        "exam_strategy": "（一）俐落開標：出名人移轉所有權屬有權處分，第三人確定取得所有權。\n（二）法理論證：引述最高法院108年度台上大字第1719號裁定，說明借名登記內部委任關係不生物權效力。\n（三）救濟途徑：借名人僅得向出名人主張民法第226條給付不能損害賠償或第179條不當得利。"
    },
    "111憲判16": {
        "case_id": "憲法法庭 111年憲判字第16號判決",
        "title": "司法警察（官）強制採尿取證案",
        "topic": "刑事訴訟法第205條之2警察強制採尿合憲性與正當法律程序",
        "timeline_stages": [
            {
                "stage": "原因案件一審",
                "court": "臺灣桃園地方法院",
                "case_no": "108年度毒聲字第350號刑事裁定",
                "ruling": "駁回聲請人撤銷處分之聲請",
                "holding_summary": "地方法院認為司法警察依刑事訴訟法第205條之2規定，有相當理由認為採取尿液得作為犯罪證據者，得違反受拘捕人之意思強制採尿，程序合法。"
            },
            {
                "stage": "原因案件抗告審",
                "court": "臺灣高等法院",
                "case_no": "108年度毒抗字第820號刑事裁定",
                "ruling": "抗告駁回確定",
                "holding_summary": "高等法院維持原審見解，認定警察具備法定強制處分權限，毋庸法院令狀或檢察官許可，裁定確定。"
            },
            {
                "stage": "憲法法庭受理審查",
                "court": "憲法法庭",
                "case_no": "111年憲判字第16號案件",
                "ruling": "受理裁判憲法審查與規範違憲審查",
                "holding_summary": "聲請人主張刑事訴訟法第205條之2將侵入性取證權限完全委由警察裁量，欠缺事前法官令狀審查與事後救濟，侵害憲法第8條人身自由與第22條身體資訊隱私權。"
            },
            {
                "stage": "憲法法庭終局判決",
                "court": "憲法法庭",
                "case_no": "111年憲判字第16號判決",
                "ruling": "宣告違憲定期失效＋過渡令狀審查程序",
                "holding_summary": "刑事訴訟法第205條之2規範牴觸憲法第8條及第22條，違憲定期失效！過渡期間強制採尿原則上應報請檢察官核發鑑定許可書；非侵入性採尿如情況急迫，應於採尿後24小時內陳報檢察官許可，否則不得作為證據。"
            }
        ],
        "distinguishing_insight": "審級演變體現了『偵查便利性』與『正當法律程序原則』的憲法位階衝突。一二審僅著眼於文義解釋，憲法法庭則依比例原則與令狀原則進行合憲性限縮。",
        "exam_strategy": "（一）開標指出警方未獲令狀許可之強制採尿違反正當法律程序。\n（二）引述111年憲判字第16號判決之過渡法規範要件（事前許可或24小時陳報）。\n（三）涵攝至刑事訴訟法第158條之4權衡法則，排除違法採尿之證據能力。"
    },
    "109台上大908": {
        "case_id": "最高法院 109 年度台上大字第 908 號民事大法庭裁定",
        "title": "侵權行為侵害純粹經濟上損失之損害賠償責任案",
        "topic": "民法第184條第1項前段之保護法益是否包含純粹經濟上損失",
        "timeline_stages": [
            {
                "stage": "一審事實審",
                "court": "臺灣新北地方法院",
                "case_no": "106年度訴字第1500號民事判決",
                "ruling": "部分勝訴、部分駁回",
                "holding_summary": "一審認定被告過失挖斷地下電纜，導致原告工廠停電停工蒙受營業損失，雖屬純經濟損失，仍構成過失侵權。"
            },
            {
                "stage": "二審上訴審",
                "court": "臺灣高等法院",
                "case_no": "107年度上易字第650號民事判決",
                "ruling": "維持部分駁回見解",
                "holding_summary": "高等法院對純粹經濟損失是否得依民法第184條第1項前段請求，實務各庭標準不一，引發上訴法律審爭議。"
            },
            {
                "stage": "三審大法庭終局定錨",
                "court": "最高法院民事大法庭",
                "case_no": "109年度台上大字第908號裁定",
                "ruling": "終局定錨：民法第184條第1項前段不保護純粹經濟上損失！",
                "holding_summary": "民法第184條第1項前段所稱之『權利』，指私法上之既有特定權利（如所有權、人格權），不包含純粹經濟上損失。純粹經濟上損失僅得依同條第1項後段（故意背於善良風俗）或第2項（違反保護他人法律）請求。"
            }
        ],
        "distinguishing_insight": "釐清德國法與我國侵權行為法體系之三大類型：權利侵權、利益侵權與違反保護法規侵權。此裁定為近十年侵權行為法最具指標性之定錨裁定。",
        "exam_strategy": "（一）開標：停電營業損失屬純粹經濟上損失，原告不得依民法第184條第1項前段請求損害賠償。\n（二）論證：引述109台上大908裁定，剖析前段所保護之『權利』與後段『利益』之體系差別。\n（三）轉向探討：檢討是否該當第184條第2項違反保護他人法律或第1項後段故意背於善良風俗。"
    },
    "106亡40": {
        "case_id": "臺灣臺南地方法院 106 年度亡字第 40 號",
        "title": "澎湖空難浩劫特別災難死亡宣告事件",
        "topic": "民法第8條特別災難失蹤期間起算與證明標準",
        "timeline_stages": [
            {
                "stage": "重大事故發生",
                "court": "澎湖外海空難事件",
                "case_no": "海難/空難罹難事件",
                "ruling": "機體墜海、未尋獲遺體",
                "holding_summary": "當事人搭乘航機墜海，經搜救後未發現生還者，亦無法尋獲大體，家屬陷入親屬繼承與保險金給付僵局。"
            },
            {
                "stage": "地方法院事實審裁定（權威創新）",
                "court": "臺灣臺南地方法院",
                "case_no": "106年度亡字第40號民事裁定",
                "ruling": "准予特別災難死亡宣告（失蹤滿1年）",
                "holding_summary": "法院創見認定：航空器重大失事落海具有高度死亡蓋然性，符合民法第8條第3項之『特別災難』，失蹤滿1年即得聲請死亡宣告，並推定於特別災難終了時死亡。"
            },
            {
                "stage": "最高法院後續定錨參照",
                "court": "最高法院民事庭",
                "case_no": "110年度台上字第4015號判決",
                "ruling": "延伸確認特別災難之公證力標準",
                "holding_summary": "最高法院參酌相關裁判，進一步確立特別災難所涉及之官方搜救調查報告具備公文書之推定實質證明力。"
            }
        ],
        "distinguishing_insight": "本案展現民法親屬繼承法中『普通失蹤 (7年/80歲滿3年)』與『特別災難 (1年)』之關鍵要件區別，是司法特考與律師一試/二試民總的必考事實範本。",
        "exam_strategy": "（一）區辨特別災難：空難、海難、大地震屬不可抗力且生還機率極低之重大事故，符合民法第8條第3項特別災難。\n（二）期間起算：自災難終了之時起算滿1年，得由利害關係人向管轄地院聲請死亡宣告。"
    },
    "108台上大897": {
        "case_id": "最高法院 108 年度台上大字第 897 號民事大法庭裁定",
        "title": "保險法第64條解除權與民法第92條詐欺撤銷權競合案",
        "topic": "要保人詐欺未據實說明時，保險人於保險法2年除斥期間經過後，得否依民法第92條撤銷契約",
        "timeline_stages": [
            {
                "stage": "一審事實審",
                "court": "地方法院民事庭",
                "case_no": "請求給付保險金事件",
                "ruling": "原告勝訴（受益人勝訴）",
                "holding_summary": "一審認為保險法第64條第3項定有2年除斥期間，立法目的在早日確定法律關係，保險人逾2年即不得再以詐欺為由撤銷。"
            },
            {
                "stage": "二審上訴審",
                "court": "高等法院民事庭",
                "case_no": "上訴審判決",
                "ruling": "見解發生重大歧異",
                "holding_summary": "高等法院各庭見解不一，部分認為特別法優先於普通法，部分認為兩者規範目的不同，得競合行使。"
            },
            {
                "stage": "大法庭終局定錨裁定",
                "court": "最高法院民事大法庭",
                "case_no": "108年度台上大字第897號裁定",
                "ruling": "終局定錨：採「特別法排除普通法說」！",
                "holding_summary": "要保人故意隱匿或為不實說明，保險人行使解除權應專依保險法第64條第3項規定。逾2年除斥期間後，保險人不得再行主張依民法第92條第1項撤銷意思表示！"
            }
        ],
        "distinguishing_insight": "保險法作為民法特別法之體系規範意旨：維護被保險人利益與法律關係確定性，避免保險人無限期藉詐欺撤銷規避理賠責任。",
        "exam_strategy": "（一）開標：保險人不得逾2年後再依民法第92條撤銷保險契約。\n（二）引述108台上大897裁定：保險法第64條第3項具備特別除斥期間之排他性。"
    },
    "108台上大3594": {
        "case_id": "最高法院 108 年度台上大字第 3594 號刑事大法庭裁定",
        "title": "販賣毒品罪既遂與未遂認定標準案",
        "topic": "販賣毒品罪之既遂標準（買賣契約成立說 vs 交付毒品/移轉所有權說）",
        "timeline_stages": [
            {
                "stage": "一二審事實審實務分歧",
                "court": "各級法院事實審",
                "case_no": "違反毒品危害防制條例案件",
                "ruling": "既遂與未遂判決重大歧異",
                "holding_summary": "以往最高法院判例（如67年台上字第2500號）採『買賣契約成立說』，只要雙方意思表示合致即成立既遂；但亦有判決認為尚未交付毒品與價金，僅成立未遂。"
            },
            {
                "stage": "刑事大法庭終局定錨裁定",
                "court": "最高法院刑事大法庭",
                "case_no": "108年度台上大字第3594號裁定",
                "ruling": "終局定錨：採「交付毒品/完成交易說」始成立既遂！",
                "holding_summary": "販賣毒品罪以營利為目的，必須已實行交付毒品，或收受價金而移轉毒品占有時，始成立販賣既遂；若僅達成買賣意思合致而尚未交付，僅成立販賣毒品未遂罪！以往採契約合致即既遂之判例決議均不再適用。"
            }
        ],
        "distinguishing_insight": "刑事實體法重大突破：揚棄將民事法之諾成契約概念直接套用至重罪既遂標準，回歸刑法客觀法益危險與著手實行之教義學原貌。",
        "exam_strategy": "（一）開標：甲乙雖已談妥毒品價格，但警方查獲時尚未交付毒品，甲僅成立販賣第一級毒品未遂罪。\n（二）論述大法庭定錨變更舊判例：引述108台上大3594裁定，明確指出舊實務買賣成立說已被廢棄。"
    },
    "110上15": {
        "case_id": "最高行政法院 110 年度上字第 15 號判決",
        "title": "地方議會議員停權處分與司法審查界線案",
        "topic": "地方議會依自律規則對議員作成停止出席會議（停權）處分之法律性質與司法救濟途徑",
        "timeline_stages": [
            {
                "stage": "地方議會內部自律懲戒",
                "court": "新竹縣議會紀律委員會與臨時會",
                "case_no": "第19屆第10次臨時會停權決議",
                "ruling": "通過停止出席臨時會會議之懲戒處分",
                "holding_summary": "新竹縣議會以議員余筱菁臉書言論詆毀議會名譽為由，依自律辦法決議處以停權懲戒。"
            },
            {
                "stage": "一審行政訴訟事實審",
                "court": "臺北高等行政法院",
                "case_no": "109年度訴字第774號判決",
                "ruling": "原告勝訴（確認停權決議違法）",
                "holding_summary": "一審判決認定停權處分已實質剝奪議員出席、質詢與表決之民選公職職權，非純屬內部秩序事項，得受司法審查，且該處分違反法律保留與比例原則，判決確認違法。"
            },
            {
                "stage": "最高行政法院法律審終局定錨",
                "court": "最高行政法院第一庭",
                "case_no": "110年度上字第15號判決",
                "ruling": "廢棄原判決，發回臺北高等行政法院更為審理",
                "holding_summary": "最高行政法院肯定議員受停權處分干預法定職權，具備行政訴訟權利保護必要；惟原審對自律規則授權依據、議會自律權與司法審查密度之限度事實調查未盡，爰廢棄發回更審。"
            }
        ],
        "distinguishing_insight": "公法學界與司法實務劃時代指標：全面突破傳統特別權力關係與議會絕對自律之藩籬，確立民意代表公法上權益受侵害時得循行政訴訟確認訴訟救濟之憲政權利保護基石。",
        "exam_strategy": "（一）區辨議會自律與司法審查：引述釋字381、499及最高行110上15判決，論述停權處分直接限制民選代表公法權能，非單純內部自律，具外在法效性與權利保護必要。\n（二）訴訟類型選擇：因停權期滿已執行完畢，原告得依行政訴訟法第6條提起確認訴訟以洗刷名譽。\n（三）實體合憲合法性：檢討地方制度法第31條是否符合法律保留原則及比例原則。"
    }
}

def get_precedent_history_chain(case_id: str) -> Optional[Dict[str, Any]]:
    """根據案號檢索裁判審級更迭與歷審脈絡鏈 (Judgement History / Instance Pipeline)"""
    if not case_id:
        return None
    try:
        from legal_summarizer_engine import parse_case_abbreviation_query, match_case_abbreviation
        parsed = parse_case_abbreviation_query(case_id)
        for k, v in PRESET_JUDGEMENT_HISTORIES.items():
            if match_case_abbreviation(parsed, {"case_id": v.get("case_id", k), "title": v.get("title", "")}):
                return v
    except Exception:
        pass
    clean_id = re.sub(r'[\s\-_]+', '', case_id).lower()
    for k, v in PRESET_JUDGEMENT_HISTORIES.items():
        if k in clean_id or clean_id in k:
            return v
        cid = re.sub(r'[\s\-_]+', '', v.get("case_id", "")).lower()
        if cid in clean_id or clean_id in cid:
            return v
    nums = re.findall(r'\d+', clean_id)
    if nums and len(nums) >= 2:
        for k, v in PRESET_JUDGEMENT_HISTORIES.items():
            k_nums = re.findall(r'\d+', k)
            if k_nums == nums:
                return v
    return None

def generate_judicial_search_urls(query: str, subject: str = "") -> Dict[str, str]:
    """生成通往司法院裁判書開放系統、法學資料檢索系統、憲法法庭與立法院等官方權威法學資料庫的即時直連查詢連結"""
    import urllib.parse
    clean_q = re.sub(r'[\r\n\t]+', ' ', query).strip()
    # 若為判決字號或公文字號（包含年度、號、判決或英數代號），保留完整案號精準檢索
    if any(k in clean_q for k in ['年度', '年', '字', '號', '院', '判', '裁', '釋', '法']) and len(clean_q) <= 45:
        search_keyword = clean_q
    else:
        tokens = [t for t in re.split(r'[\s,，、。！？]+', clean_q) if len(t) >= 2]
        search_keyword = " ".join(tokens[:4]) if tokens else clean_q[:25]
    encoded_k = urllib.parse.quote(search_keyword)

    return {
        "🏛️ 司法院 30 年裁判書全文開放檢索 (全台法院)": f"https://judgment.judicial.gov.tw/FJUD/default.aspx?k={encoded_k}",
        "⚖️ 司法院法學資料檢索系統 (裁判與判例要旨)": "https://jirs.judicial.gov.tw/Index.aspx",
        "📜 憲法法庭裁判與司法院大法官解釋系統": f"https://cons.judicial.gov.tw/jcc/zh-tw/jep01?q={encoded_k}",
        "📖 全國法規資料庫 (法務部法規命令與沿革)": f"https://law.moj.gov.tw/Law/LawSearchLaw.aspx?keyword={encoded_k}",
        "🏛️ 立法院法律系統 (法條立法沿革與對照)": "https://lis.ly.gov.tw/lglawc/lglawkm",
        "📜 司法院公報查詢系統 (裁判公報檢索)": "https://gaze.judicial.gov.tw/",
        "🏢 智慧財產及商業法院裁判檢索": "https://ipc.judicial.gov.tw/tw/lp-66-071.html"
    }

def search_precedents_advanced(
    court_system: str = "全部法院 (全體司法體系)",
    jud_year: str = "",
    jud_word: str = "全部字別 (不限)",
    jud_no: str = "",
    case_cause: str = "",        # 裁判案由 (jt)
    main_holding: str = "",      # 裁判主文/心證 (jmain/txtopinion)
    argument_issue: str = "",    # 案件爭點 (txtargument)
    cited_laws: str = "",        # 相關法條 (lc1a/lc1b)
    case_type: str = "全部",     # 裁判類別 (判決/裁定/全部)
    subject: str = "全部科目",
    time_filter: str = "全部時間 (不限年份)",
    filter_no_legal_issue: bool = True,  # 排除無實質法律爭點之純程序裁定
    top_k: int = 50
) -> List[Dict[str, Any]]:
    """
    專業法學多維度司法裁判檢索：
    支援：法院層級體系、民國年度 (jud_year)、常用字別 (sel_judword)、裁判字號 (jud_no)、
    案號縮寫智慧解析（如 108台上908民、108台上大1719裁、院字2949、重上更一15）、
    裁判案由 (jt)、主文/心證 (jmain/txtopinion)、案件爭點 (txtargument)、相關法條 (lc1a/lc1b)、
    審級脈絡時間軸滑桿過濾 (time_filter)、
    爭點實質性過濾 (filter_no_legal_issue: 自動排除無實體爭鳴之純程序駁回/例行裁定，並附掛歷審案號)
    """
    catalog = get_precedents_catalog()
    if not catalog:
        return []

    results = []
    clean_year = jud_year.strip().replace("年", "").replace("度", "")
    clean_word = jud_word.strip() if jud_word != "全部字別 (不限)" else ""
    clean_no = jud_no.strip().replace("號", "").replace("字", "")
    clean_cause = case_cause.strip()
    clean_holding = main_holding.strip()
    clean_issue = argument_issue.strip()
    clean_laws = cited_laws.strip()
    law_nums = re.findall(r'\d+', clean_laws)
    target_courts = COURTS_TAXONOMY.get(court_system, [])

    # 檢查是否為縮寫查詢
    parsed_abbr = None
    try:
        from legal_summarizer_engine import parse_case_abbreviation_query, match_case_abbreviation
        combined_citation = f"{clean_year}{clean_word}{clean_no}".strip()
        if combined_citation:
            parsed_abbr = parse_case_abbreviation_query(combined_citation)
    except Exception:
        parsed_abbr = None

    for item in catalog:
        score = 0
        cid = item.get("case_id", "")
        ct = item.get("court", "")
        lvl = item.get("level", "")
        tit = item.get("title", "")
        sub_c = item.get("sub_category", "")
        hold = item.get("holding", "")
        iss = item.get("issue", "")
        sch = item.get("scholarly_views", "")
        laws = " ".join(item.get("laws_cited", []))
        item_sub = item.get("subject", "")

        # 縮寫精確命中加權
        if parsed_abbr and match_case_abbreviation(parsed_abbr, item):
            score += 120

        # 審級脈絡時間軸過濾 (JudgementChain Time Filter)
        if time_filter and "全部時間" not in time_filter:
            min_roc_year = 0
            if "近 1 年" in time_filter:
                min_roc_year = 113
            elif "近 3 年" in time_filter:
                min_roc_year = 111
            elif "近 5 年" in time_filter:
                min_roc_year = 109
            elif "近 10 年" in time_filter:
                min_roc_year = 104
            elif "近 30 年" in time_filter:
                min_roc_year = 84

            if min_roc_year > 0:
                roc_y = extract_case_roc_year(item)
                if roc_y < min_roc_year:
                    continue

        # 1. 法院體系過濾
        if target_courts:
            if not any(tc in ct or tc in lvl or tc in cid for tc in target_courts):
                continue
            score += 10
        elif court_system and "全部" not in court_system:
            if court_system not in ct and court_system not in lvl and court_system not in cid:
                continue
            score += 10

        # 2. 民國年度 (jud_year)
        if clean_year:
            year_patterns = [f"{clean_year}年度", f"{clean_year}年", f" {clean_year} ", f"_{clean_year}_"]
            if any(yp in cid for yp in year_patterns) or bool(re.search(rf'(?<!\d){re.escape(clean_year)}(?!\d)', cid)):
                score += 35
            else:
                continue

        # 3. 常用字別 (sel_judword)
        if clean_word:
            if clean_word == '上':
                if not re.search(r'(?<![台重勞家加])上(?!大|訴|易)', cid):
                    continue
            elif clean_word == '抗':
                if not re.search(r'(?<![台])抗(?!大)', cid):
                    continue
            else:
                if clean_word not in cid:
                    continue
            score += 35

        # 4. 案號數字 (jud_no)
        if clean_no:
            if not re.search(rf'(?<!\d){re.escape(clean_no)}(?!\d)', cid):
                continue
            score += 50

        # 5. 裁判與實務見解類別 (全部/判決/裁定/原判例/最高院/最高行決議/高院法律座談會/憲法裁判/大法官解釋)
        if case_type != "全部":
            full_record_str = f"{cid} {lvl} {ct} {tit} {sub_c}"
            if case_type == "判決":
                if not ("判決" in lvl or "判決" in cid or "憲判" in cid or "判" in cid):
                    continue
            elif case_type == "裁定":
                if not ("裁定" in lvl or "裁定" in cid or "憲裁" in cid or "裁" in cid):
                    continue
            elif case_type == "原判例":
                if not ("判例" in full_record_str):
                    continue
            elif case_type in ["最高院/最高行決議", "最高法院/最高行決議"]:
                if not any(k in full_record_str for k in ["決議", "庭長法官聯席會議", "民事庭會議", "刑事庭會議"]):
                    continue
            elif case_type in ["高院法律座談會", "法律座談會"]:
                if not ("座談會" in full_record_str):
                    continue
            elif case_type in ["憲法裁判/大法官解釋", "大法官解釋"]:
                if not any(k in full_record_str for k in ["釋字", "憲判", "憲裁", "憲法法庭", "大法官"]):
                    continue
            score += 15

        # 6. 裁判案由 (jt)
        if clean_cause:
            try:
                from legal_summarizer_engine import BooleanQueryParser, evaluate_boolean_query
                if BooleanQueryParser.is_boolean_query(clean_cause):
                    if not evaluate_boolean_query(clean_cause, f"{tit} {sub_c} {iss}"):
                        continue
                    score += 50
                else:
                    cause_tokens = [t for t in re.split(r'[\s,，、]+', clean_cause) if len(t) >= 2] or [clean_cause]
                    matched_c = sum(1 for tok in cause_tokens if tok in tit or tok in sub_c or tok in iss)
                    if matched_c == 0:
                        continue
                    score += 25 * matched_c
            except Exception:
                pass

        # 7. 裁判主文 / 法院心證 (jmain / txtopinion)
        if clean_holding:
            try:
                from legal_summarizer_engine import BooleanQueryParser, evaluate_boolean_query
                if BooleanQueryParser.is_boolean_query(clean_holding):
                    if not evaluate_boolean_query(clean_holding, f"{hold} {sch}"):
                        continue
                    score += 60
                else:
                    h_tokens = [t for t in re.split(r'[\s,，、。]+', clean_holding) if len(t) >= 2] or [clean_holding]
                    matched_h = sum(1 for tok in h_tokens if tok in hold or tok in sch)
                    if matched_h == 0:
                        continue
                    score += 20 * matched_h
            except Exception:
                pass

        # 8. 案件爭點 (txtargument)
        if clean_issue:
            try:
                from legal_summarizer_engine import BooleanQueryParser, evaluate_boolean_query
                if BooleanQueryParser.is_boolean_query(clean_issue):
                    if not evaluate_boolean_query(clean_issue, f"{iss} {tit} {sub_c}"):
                        continue
                    score += 60
                else:
                    i_tokens = [t for t in re.split(r'[\s,，、。]+', clean_issue) if len(t) >= 2] or [clean_issue]
                    matched_i = sum(1 for tok in i_tokens if tok in iss or tok in tit or tok in sub_c)
                    if matched_i == 0:
                        continue
                    score += 20 * matched_i
            except Exception:
                pass

        # 9. 相關法條 (lc1a / lc1b)
        if clean_laws:
            matched_l = False
            for tok in [t for t in re.split(r'[\s,，、]+', clean_laws) if len(t) >= 2]:
                if tok in laws:
                    matched_l = True
                    score += 25
            for num in law_nums:
                if any(num in law for law in item.get("laws_cited", [])):
                    matched_l = True
                    score += 20
            if not matched_l:
                continue

        # 10. 科目領域匹配
        if subject and "全部" not in subject:
            sub_kws = [k for k in re.split(r'[\s（）()【】/・、,，]+', subject) if len(k) >= 2]
            if any(k in item_sub or k in tit for k in sub_kws):
                score += 15

        if "大法庭" in lvl:
            score += 15
        elif "憲法" in lvl:
            score += 10

        results.append((score, item))

    # 爭點實質性篩選與歷審脈絡鏈掛載 (貫徹指示：排除欠缺法律爭點之裁判，並高度注重歷審裁判)
    from legal_judgment_analyzer import evaluate_judgment_substance

    # 若未指定任何具體條件但點選查詢，預設自目錄依序挑選
    if not (clean_year or clean_word or clean_no or clean_cause or clean_holding or clean_issue or clean_laws or target_courts or (court_system and "全部" not in court_system)):
        candidates = catalog
    else:
        results.sort(key=lambda x: -x[0])
        candidates = [r[1] for r in results]

    final_results = []
    for it in candidates:
        cid = it.get("case_id", "")
        hold = it.get("holding", "")
        iss = it.get("issue", "")
        full_sample = f"{hold} {iss}"
        substance = evaluate_judgment_substance(full_sample, title=cid, doc_type=it.get("level", ""))
        
        # 若啟用排除無實質爭點裁判：過濾純程序駁回、未繳費、程式不合、例行量刑
        if filter_no_legal_issue and not substance.get("has_legal_issue", True):
            continue

        item_out = dict(it)
        item_out["has_legal_issue"] = substance.get("has_legal_issue", True)
        item_out["is_procedural_dismissal"] = substance.get("is_procedural_dismissal", False)
        item_out["discard_reason"] = substance.get("discard_reason", "")
        item_out["extracted_history_instances"] = substance.get("extracted_history_instances", [])
        item_out["substantive_prior_instance"] = substance.get("substantive_prior_instance")
        final_results.append(item_out)
        if len(final_results) >= top_k:
            break

    # 補充自 SQLite 百萬裁判大庫 (若目錄筆數不足)
    if len(final_results) < top_k:
        try:
            from build_million_judgments_db import get_million_db_engine
            db_engine = get_million_db_engine()
            db_hits = db_engine.search_fts_and_meta(
                jud_year=clean_year,
                jud_word=clean_word,
                jud_no=clean_no,
                case_cause=clean_cause,
                main_holding=clean_holding,
                argument_issue=clean_issue,
                cited_laws=clean_laws,
                case_type=case_type,
                court_system=court_system,
                filter_no_legal_issue=filter_no_legal_issue,
                top_k=(top_k - len(final_results))
            )
            seen_ids = {x.get("case_id") for x in final_results}
            for dh in db_hits:
                cid = dh.get("case_id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    dh_item = {
                        "case_id": cid,
                        "court": dh.get("court", ""),
                        "level": dh.get("level", "司法裁判"),
                        "subject": dh.get("subject", "法學專業實務"),
                        "sub_category": dh.get("title", cid),
                        "title": dh.get("title", cid),
                        "laws_cited": [x.strip() for x in (dh.get("laws_cited") or "").split("、") if x.strip()],
                        "issue": dh.get("issue", ""),
                        "holding": dh.get("holding_preview", ""),
                        "scholarly_views": "",
                        "exam_application_hint": "",
                        "has_legal_issue": bool(dh.get("has_legal_issue", 1)),
                        "extracted_history_instances": []
                    }
                    final_results.append(dh_item)
        except Exception:
            pass

    return final_results



def search_local_precedents(
    query: str,
    subject: str = "",
    top_k: int = 6,
    court_categories: Optional[List[str]] = None,
    cause_of_action: str = "",
    opinion: str = "",
    argument: str = "",
    statute_target: str = "",
    case_year: str = "",
    case_word: str = "",
    case_num: str = "",
    time_filter: str = "全部時間 (不限年份)",
    filter_no_legal_issue: bool = True
) -> List[Dict[str, Any]]:
    """
    從 1,256 筆權威判解庫中高速篩選最相關之判決/大法庭裁定
    支援專業多欄位檢索：審級分類、裁判案由、法院心證、案件爭點、相關法條與常用字別組合
    支援案號縮寫智慧匹配（如 108台上908民、108台上大1719裁、院字2949、重上更一15）
    支援時間軸過濾滑桿 (time_filter)
    """
    catalog = get_precedents_catalog()
    if not catalog:
        return []

    # 1. 組合綜合查詢字串
    query_parts = [query.strip()]
    if cause_of_action.strip():
        query_parts.append(cause_of_action.strip())
    if opinion.strip():
        query_parts.append(opinion.strip())
    if argument.strip():
        query_parts.append(argument.strip())
    if statute_target.strip():
        query_parts.append(statute_target.strip())
    full_query = " ".join([p for p in query_parts if p])

    # 2. 拆分原始 tokens 與 n-gram
    raw_tokens = [t.strip() for t in re.split(r'[\s,，、。！？]+', full_query) if len(t.strip()) >= 2]
    if not raw_tokens:
        raw_tokens = [full_query.strip()] if full_query.strip() else [""]

    ngram_tokens = set(raw_tokens)
    for raw in raw_tokens:
        if len(raw) > 2:
            for n in [2, 3, 4]:
                for i in range(len(raw) - n + 1):
                    ngram_tokens.add(raw[i:i+n])
    tokens = list(ngram_tokens)
    numbers = re.findall(r'\d+', full_query)

    # 支援案號縮寫智慧解析
    parsed_abbr = None
    try:
        from legal_summarizer_engine import parse_case_abbreviation_query, match_case_abbreviation
        combined_citation = f"{case_year}{case_word}{case_num}".strip() or query.strip()
        if combined_citation:
            parsed_abbr = parse_case_abbreviation_query(combined_citation)
    except Exception:
        parsed_abbr = None

    # 支援專業布林邏輯精確篩選 (Boolean Query)
    is_bool_query = False
    try:
        from legal_summarizer_engine import BooleanQueryParser, evaluate_boolean_query
        if BooleanQueryParser.is_boolean_query(query) or BooleanQueryParser.is_boolean_query(full_query):
            is_bool_query = True
    except Exception:
        is_bool_query = False

    scored_items = []
    for item in catalog:
        case_id = item.get("case_id", "")
        level = item.get("level", "")
        court = item.get("court", "")
        title = item.get("title", "")
        sub_cat = item.get("sub_category", "")
        issue = item.get("issue", "")
        holding = item.get("holding", "")
        scholarly = item.get("scholarly_views", "")
        laws_cited = item.get("laws_cited", [])

        # 審級脈絡時間軸過濾 (JudgementChain Time Filter)
        if time_filter and "全部時間" not in time_filter:
            min_roc_year = 0
            if "近 1 年" in time_filter:
                min_roc_year = 113
            elif "近 3 年" in time_filter:
                min_roc_year = 111
            elif "近 5 年" in time_filter:
                min_roc_year = 109
            elif "近 10 年" in time_filter:
                min_roc_year = 104
            elif "近 30 年" in time_filter:
                min_roc_year = 84

            if min_roc_year > 0:
                roc_y = extract_case_roc_year(item)
                if roc_y < min_roc_year:
                    continue

        # 專業法學庫審級分類篩選 (court_categories)
        if court_categories:
            cat_match = False
            for cat in court_categories:
                if cat in level or cat in court or cat in case_id:
                    cat_match = True
                    break
                if cat == "憲法位階" and any(k in level for k in ["憲法", "大法官"]):
                    cat_match = True
                    break
                if cat == "大法庭" and "大法庭" in level:
                    cat_match = True
                    break
            if not cat_match:
                continue

        score = 0
        text_pool = f"{case_id} {court} {level} {title} {sub_cat} {issue} {holding} {scholarly} {' '.join(laws_cited)}"

        # 若使用者輸入專業布林查詢，先進行布林真值求值
        if is_bool_query:
            target_bool_q = query if BooleanQueryParser.is_boolean_query(query) else full_query
            if not evaluate_boolean_query(target_bool_q, text_pool):
                continue
            score += 100

        # 案號縮寫智慧命中加權
        if parsed_abbr and match_case_abbreviation(parsed_abbr, item):
            score += 150

        # 專業法學庫進階錨點 1: 年度 + 常用字別 + 案號 精準命中
        if case_year.strip() and re.search(rf'(?<!\d){re.escape(case_year.strip())}(?!\d)', case_id):
            score += 30
        if case_word.strip():
            cw = case_word.strip()
            if cw == '上':
                if re.search(r'(?<![台重勞家加])上(?!大|訴|易)', case_id):
                    score += 45
            elif cw == '抗':
                if re.search(r'(?<![台])抗(?!大)', case_id):
                    score += 45
            else:
                if cw in case_id:
                    score += 45
        if case_num.strip() and re.search(rf'(?<!\d){re.escape(case_num.strip())}(?!\d)', case_id):
            score += 60

        # 專業法學庫進階錨點 2: 裁判案由 (cause_of_action)
        if cause_of_action.strip():
            for c_tok in re.split(r'[\s,，、]+', cause_of_action.strip()):
                if len(c_tok) >= 2 and (c_tok in title or c_tok in sub_cat or c_tok in issue):
                    score += 40

        # 專業法學庫進階錨點 3: 法院心證 (opinion)
        if opinion.strip():
            for o_tok in re.split(r'[\s,，、]+', opinion.strip()):
                if len(o_tok) >= 2 and (o_tok in holding or o_tok in scholarly):
                    score += 40

        # 專業法學庫進階錨點 4: 案件爭點 (argument)
        if argument.strip():
            for a_tok in re.split(r'[\s,，、]+', argument.strip()):
                if len(a_tok) >= 2 and (a_tok in issue or a_tok in title or a_tok in sub_cat):
                    score += 40

        # 專業法學庫進階錨點 5: 相關法條 (statute_target)
        if statute_target.strip():
            for s_tok in re.split(r'[\s,，、]+', statute_target.strip()):
                if len(s_tok) >= 2 and any(s_tok in law for law in laws_cited):
                    score += 45

        # 大法庭與憲法裁判權重加成
        if "大法庭" in level:
            score += 15
        elif "憲法" in level or "大法官" in level:
            score += 10

        # 科目匹配加成
        item_sub = item.get("subject", "")
        if subject and "全部" not in subject:
            sub_keywords = [w.strip() for w in re.split(r'[\s（）()【】/・、,，]+', subject) if len(w.strip()) >= 2]
            if any(k in item_sub or k in title for k in sub_keywords):
                score += 15

        # 雙向匹配 A：查詢 token 是否出現在文字池
        for tok in tokens:
            if tok and tok in text_pool:
                score += 8
                if tok in title or tok in sub_cat:
                    score += 16
                if tok in case_id:
                    score += 25

        # 雙向匹配 B：判決的關鍵爭點/次分類名稱是否出現在使用者的查詢句子中
        if sub_cat and len(sub_cat) >= 2 and sub_cat in full_query:
            score += 35
        if title and len(title) >= 4 and any(title[i:i+4] in full_query for i in range(len(title)-3)):
            score += 25

        # 法條完全命中計分
        for law in laws_cited:
            if any(tok in law for tok in raw_tokens if tok):
                score += 25
            if any(num in law for num in numbers if len(num) >= 2):
                score += 15

        # 判決字號數字命中（例如 1719、16）
        if any(num in case_id for num in numbers if len(num) >= 2):
            score += 30

        if score > 0:
            scored_items.append((score, item))

    scored_items.sort(key=lambda x: -x[0])

    # 爭點實質性篩選與歷審案號 enrichment
    from legal_judgment_analyzer import evaluate_judgment_substance
    candidate_list = [x[1] for x in scored_items]

    # 智慧保底機制：若未直接命中且指定了考科
    if not candidate_list and subject and "全部" not in subject:
        candidate_list = [
            it for it in catalog
            if any(k in it.get("subject", "") for k in re.split(r'[\s（）()【】/・、,，]+', subject) if len(k) >= 2)
        ]

    final_precedents = []
    for it in candidate_list:
        cid = it.get("case_id", "")
        hold = it.get("holding", "")
        iss = it.get("issue", "")
        substance = evaluate_judgment_substance(f"{hold} {iss}", title=cid, doc_type=it.get("level", ""))

        if filter_no_legal_issue and not substance.get("has_legal_issue", True):
            continue

        item_out = dict(it)
        item_out["has_legal_issue"] = substance.get("has_legal_issue", True)
        item_out["is_procedural_dismissal"] = substance.get("is_procedural_dismissal", False)
        item_out["discard_reason"] = substance.get("discard_reason", "")
        item_out["extracted_history_instances"] = substance.get("extracted_history_instances", [])
        item_out["substantive_prior_instance"] = substance.get("substantive_prior_instance")
        final_precedents.append(item_out)
        if len(final_precedents) >= top_k:
            break

    return final_precedents

def get_precedent_by_id(case_id: str) -> Optional[Dict[str, Any]]:
    """根據案號（精確、包含、關鍵字或智慧縮寫如 108台上908民、108台上大1719裁、院字2949、重上更一15）從裁判庫中獲取裁判卡片"""
    if not case_id:
        return None

    # 0. 縮寫智慧匹配
    parsed = None
    try:
        from legal_summarizer_engine import parse_case_abbreviation_query, match_case_abbreviation, BUILTIN_LANDMARK_DOCS
        parsed = parse_case_abbreviation_query(case_id)

        # 優先搜尋 BUILTIN_LANDMARK_DOCS
        for b in BUILTIN_LANDMARK_DOCS:
            if match_case_abbreviation(parsed, {"case_id": b.get("title", ""), "title": b.get("title", "")}):
                return {
                    "case_id": b.get("title", ""),
                    "court": b.get("doc_type", "法院"),
                    "level": b.get("doc_type", "裁判"),
                    "subject": "實體與程序法",
                    "title": b.get("title", ""),
                    "holding": b.get("text", "")[:400] + "...",
                    "laws_cited": [],
                    "issue": "本案裁判爭點與實質審級攻防",
                    "scholarly_views": "權威學說與司法實務經典定錨。",
                    "exam_application_hint": "司律二試上位卷作答關鍵先例。"
                }
    except Exception:
        parsed = None

    catalog = get_precedents_catalog()
    if not catalog:
        return None

    if parsed:
        for r in catalog:
            if match_case_abbreviation(parsed, r):
                return r

    clean_id = re.sub(r'[\s\-_]+', '', case_id).lower()

    # 1. 完全或前綴/後綴匹配
    for r in catalog:
        cid = re.sub(r'[\s\-_]+', '', r.get("case_id", "")).lower()
        if cid == clean_id:
            return r

    # 2. 包含匹配
    for r in catalog:
        cid = re.sub(r'[\s\-_]+', '', r.get("case_id", "")).lower()
        if clean_id in cid or cid in clean_id:
            return r

    # 3. 案號核心數字與中文字號比對 (例如 108台上大1719)
    nums = re.findall(r'\d+', clean_id)
    chars = re.findall(r'[\u4e00-\u9fa5]+', clean_id)
    if nums and chars:
        for r in catalog:
            cid = re.sub(r'[\s\-_]+', '', r.get("case_id", "")).lower()
            if all(n in cid for n in nums) and any(c in cid for c in chars if len(c) >= 2):
                return r
    return None

def get_all_precedent_options() -> List[str]:
    """獲取供 UI 下拉選單快速挑選之裁判格式標籤（依審級與重要性排序）"""
    catalog = get_precedents_catalog()
    options = []
    for r in catalog:
        cid = r.get("case_id", "")
        court = r.get("court", "")
        lvl = r.get("level", "")
        tit = r.get("title", "")
        if cid:
            tag = f"{cid} ｜ {court} ｜ {tit[:22]}"
            options.append(tag)
    return options


class LegalIssueQueryEngine:
    def __init__(self, model_name=DEFAULT_GEMINI_MODEL):
        self.api_key = get_gemini_api_key()
        if not self.api_key:
            raise ValueError("未檢測到 GEMINI_API_KEY！請在 Streamlit Secrets 或 .env 中設定您的 API Key。")
        self.model_name = model_name
        if USE_MODERN_GENAI:
            self.client = genai.Client(api_key=self.api_key)
        else:
            legacy_genai.configure(api_key=self.api_key)
            self.model = legacy_genai.GenerativeModel(model_name=model_name)

    def _call_model(self, prompt: str) -> str:
        models_to_try = get_gemini_models_to_try(self.model_name)
        last_err = None
        for m_name in models_to_try:
            try:
                if USE_MODERN_GENAI:
                    cfg = genai_types.GenerateContentConfig(
                        temperature=0.2
                    )
                    resp = self.client.models.generate_content(
                        model=m_name,
                        contents=prompt,
                        config=cfg
                    )
                    return resp.text
                else:
                    cur_model = legacy_genai.GenerativeModel(model_name=m_name)
                    resp = cur_model.generate_content(
                        prompt,
                        generation_config=legacy_genai.types.GenerationConfig(temperature=0.2)
                    )
                    return resp.text
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"Gemini API 查詢調用失敗: {last_err}")

    def query_legal_issue(self, query: str, subject: str = "全部科目") -> Dict[str, Any]:
        """
        執行深度法學爭點查詢
        返回包含法條構成要件、最高位階實務判決、學說肯否兩說及作答開標示範的完整字典
        """
        matched_precedents = search_local_precedents(query, subject=subject, top_k=5)

        precedent_context_str = ""
        if matched_precedents:
            precedent_context_str = "【本機權威判解庫即時檢索命中資料（供對照精確引述）】：\n"
            for idx, p in enumerate(matched_precedents, 1):
                precedent_context_str += f"""
--- 命中裁判 {idx} ---
- 裁判字號：{p.get('case_id')}
- 審級權威：{p.get('level')}
- 爭點領域：{p.get('title')} ({p.get('sub_category')})
- 核心要旨：{p.get('holding')}
- 引用法規：{', '.join(p.get('laws_cited', []))}
- 學說實務對比：{p.get('scholarly_views')}
"""

        prompt = f"""
你是一位台灣「司法官暨律師高等考試」講座名師兼前最高法院研究法官。
現在使用者提出了一項法律爭點、關鍵字或案件情境進行【AI 爭點查詢】：
查詢內容：【{query}】
指定考科：【{subject}】

{precedent_context_str}

請嚴謹、精準且完整地輸出以下五大結構化區塊（請務必依標題編排）：

### 一、📜 核心法條依據與構成要件
- 條號與法規全稱（例如：民法第184條第1項前段、保險法第64條第3項）
- 法條客觀與主觀構成要件剖析
- 法律效果說明

### 二、⚖️ 核心法律爭點所在
- 簡要提煉 1~3 個最關鍵的法律爭議核心（衝突所在與規範漏洞或解釋疑義）
- 說明爭點在國家考試與實務實務上的重要性

### 三、🏛️ 權威司法實務裁判見解（最高法院、高等法院與各審級法院代表判決）
1. **憲法法庭判決 / 大法官解釋**（若有涉基本權或違憲審查，引出案由、字號與核心主文）
2. **最高法院大法庭裁定 / 最高行政法院大法庭裁定**（引出完整年度字號，如最高法院108年度台上大字第1719號，並詳述主文與核心法理）
3. **最高法院精選裁判 / 具有參考價值裁判 / 經典判例 / 決議**（引出代表性字號與裁判要旨）
4. **高等法院 / 智慧財產及商業法院 / 高等行政法院代表性裁判**（補充具重要指標意義或事實認定典型之審級裁判與字號）

### 四、📚 學說見解深度對照（肯否兩說）
- **甲說（通說 / 實務主流見解）**：立論依據、法理基礎、代表學者（如王澤鑑、林山田、黃榮堅、陳敏、姜世明、葉啟洲教授等）
- **乙說（有力說 / 批判見解）**：立論依據、對甲說之質疑與實務適用反思
- **評析與折衷說**：法理之衡平與當前考選部命題評閱之採擇傾向

### 五、✍️ 國考二試上位卷 IRAC 作答示範（開標與涵攝指引）
- **俐落開標示範**：（例如：（一）乙移轉A屋所有權予丙，屬有權處分，丙取得所有權：）
- **大前提確立示範**：如何融合法條、大法庭裁定字號與學說見解
- **事實涵攝與結論**：如何將具體事實嚴密代入構成要件

### 六、⚠️ 裁判效力狀態與違憲警示（專業法學語意搜尋 特色功能）
- 標註本爭點涉及裁判之有效性狀態，提醒考生與實務嚴格防禦：
  - 🟢 **【現行有效主流】**：最高法院現行穩健見解或大法庭裁定
  - 🟡 **【見解歧異/變更中】**：各庭間尚有爭議、大法庭提案中
  - 🔴 **【已廢止/違憲停止適用】**：經大法庭裁定廢止、停止適用或經憲法法庭宣告違憲失效（絕對禁止在國考或訴訟中援用！）

### 七、📈 爭點實務見解演進時間軸（審級脈絡歷程脈絡樹）
- 以清晰時間箭頭流程呈現本爭點之實務演進軌跡：
  `【早期傳統舊判例】➔ 【實務紛歧與學說反思】➔ 【最高法院大法庭裁定定錨】➔ 【憲法法庭最新人權審查趨勢】`

請直接以格式清晰之 Markdown 文本輸出，內容必須專業、精準、足堪作為司律榜首等級之法學寶典！
"""
        response_text = self._call_model(prompt)

        return {
            "query": query,
            "subject": subject,
            "matched_local_precedents": matched_precedents,
            "markdown_result": response_text,
            "external_search_urls": generate_judicial_search_urls(query, subject)
        }

    def summarize_judgment(
        self,
        case_id: str,
        judgment_text: str = "",
        subject: str = ""
    ) -> Dict[str, Any]:
        """
        AI 判決深度摘要：
        依使用者需求，嚴格產出以下核心區塊：
        1. 裁判基本資訊
        2. 一、主文 (Disposition)
        3. 二、案例事實 (Case Facts)
        4. 三、案件爭點 (Legal Issues)
        5. 四、雙方所述 (Parties' Contentions: 原告/上訴人主張 vs 被告/被上訴人答辯)
        6. 五、法院心證與裁判論理 (Court's Ratio Decidendi)
        7. 六、專業評析、相似實務對照與國考作答要領 (Analysis & Exam Relevance)
        """
        local_rec = get_precedent_by_id(case_id)
        local_context = ""
        if local_rec:
            local_context = f"""
【本機權威庫已收錄之本裁判核心卡片】：
- 裁判字號：{local_rec.get('case_id')}
- 法院與審級：{local_rec.get('court')} ({local_rec.get('level')})
- 爭點領域：{local_rec.get('title')} ({local_rec.get('sub_category')})
- 核心要旨：{local_rec.get('holding')}
- 引用法規：{', '.join(local_rec.get('laws_cited', []))}
- 學說評析：{local_rec.get('scholarly_views')}
- 國考作答提示：{local_rec.get('exam_application_hint')}
"""
        user_text_context = ""
        if judgment_text.strip():
            user_text_context = f"\n【使用者提供之裁判全文或事實節錄】：\n{judgment_text.strip()[:8000]}\n"

        prompt = f"""
你是一位台灣「司法院前最高法院研究法官」兼「律師司法官高等考試權威講座名師」，擅長精準解構各級法院裁判書。
現在請針對以下司法裁判進行極致嚴謹、體系分明、高度可讀的【AI 判決精華深度摘要】：

裁判案號/字號：【{case_id}】
所屬科目領域：【{subject or '司法實務綜合'}】

{local_context}
{user_text_context}

請務必嚴格遵循以下六大標題區塊輸出完整 Markdown 報告：

### 🏛️ 裁判基本資訊
- **裁判字號**：完整案號（例：最高法院108年度台上大字第1719號民事裁定、臺灣臺南地方法院106年度亡字第40號民事裁定、臺灣高等法院115年度上字第620號判決）
- **管轄法院與審級**：所屬法院（最高法院、高等法院、高等行政法院、最高行政法院、智慧財產及商業法院或地方法院）與審級權威定位
- **涉及核心法規條號**：具體法規全稱與條項（例如：民法第184條第1項前段、第767條第1項、保險法第64條等）

### 一、📜 裁判主文 (Disposition)
- 請以清晰格式列出本案之「裁判主文」（例如：原判決廢棄，發回臺灣高等法院；上訴駁回；原告之訴駁回；宣告被繼承人於某年某月某日死亡等）。

### 二、🔍 案例客觀事實 (Case Facts)
- 當事人法律關係背景與起因（原委、契約締結、借名登記、物之交付、侵權損害發生經過或行政處分作成歷程）。
- 雙方紛爭爆發之具體時空經過與關鍵客觀事實細節。

### 三、⚖️ 案件核心法律爭點 (Legal Issues)
- 簡要提煉 1~3 項繫屬於法院的核心法律爭端（例如：借名登記出名人擅自將不動產移轉第三人是否屬無權處分？死亡宣告在特定重大空難浩劫時如何計算特別災難失蹤期間？）。

### 四、🗣️ 雙方當事人所述與攻防焦點 (Parties' Contentions)
- **原告 / 上訴人主張**：其起訴/上訴之訴訟標的、請求權基礎、主要事實陳述、為何主張他方違約/違法/侵權、援引之法理與法條。
- **被告 / 被上訴人答辯**：對事實之抗辯（如否認借名關係、抗辯善意受讓取得、消滅時效抗辯、過失相抵或不可抗力抗辯）。

### 五、⚖️ 法院心證與裁判論理 (Court's Ratio Decidendi)
- **事實認定與舉證責任分配**：法院如何認定雙方爭執之事實真相、舉證責任如何歸屬。
- **認事用法與法條涵攝**：法院對關鍵法規與制度目的之權威解釋（文義、體系、歷史與客觀目的解釋）。
- **法院心證形成的判決理由**：為何法院採信某方、駁回另一方之抗辯？關鍵之心證論理轉折為何？

### 六、🎓 專業評析、相似實務對照與國考作答要領 (Analysis & Exam Relevance)
- **法理與學說評析**：本案裁判在法學體系上的重要地位（符合通說、少數說、或是突破舊實務之劃時代定錨見解）。
- **相似權威裁判對照**：對比最高法院相關大法庭裁定、判例或其他法院之相似/相異判決（分析其同中之異、異中之同）。
- **司律二試上位卷作答要領**：若國考二試出題以此事實為藍本，考生應如何精準「開標、確立大前提、事實涵攝並下結論」，達到閱卷委員給予上位卷之高分標準！

請直接以標準、專業且結構完整的繁體中文 Markdown 輸出。
"""
        result_md = self._call_model(prompt)
        return {
            "case_id": case_id,
            "subject": subject,
            "local_record": local_rec,
            "markdown_result": result_md,
            "external_search_urls": generate_judicial_search_urls(case_id, subject)
        }

    def compare_precedents(
        self,
        case_a: str,
        case_b: str,
        text_a: str = "",
        text_b: str = "",
        topic: str = ""
    ) -> Dict[str, Any]:
        """
        AI 案例橫向比對與分歧研析：
        對比兩則裁判/大法庭裁定/判例之間的事實差異、爭點、法條、主張、心證與見解分歧
        """
        rec_a = get_precedent_by_id(case_a)
        rec_b = get_precedent_by_id(case_b)

        ctx_a = f"【裁判 A 庫存資訊】：案號={case_a} | 審級={rec_a.get('level')} | 要旨={rec_a.get('holding')} | 學說={rec_a.get('scholarly_views')}" if rec_a else f"【裁判 A】：案號={case_a}"
        ctx_b = f"【裁判 B 庫存資訊】：案號={case_b} | 審級={rec_b.get('level')} | 要旨={rec_b.get('holding')} | 學說={rec_b.get('scholarly_views')}" if rec_b else f"【裁判 B】：案號={case_b}"

        if text_a.strip():
            ctx_a += f"\n裁判 A 內容/節錄：\n{text_a.strip()[:4000]}"
        if text_b.strip():
            ctx_b += f"\n裁判 B 內容/節錄：\n{text_b.strip()[:4000]}"

        prompt = f"""
你是一位台灣「司法院法官學院講座」兼「律師司法官高等考試典試委員」，擅長裁判區別技術 (Case Distinguishing) 與實務見解脈絡比較。
現在請針對以下兩則重要司法裁判進行全方位、深度橫向對比分析：

【裁判 A】：{case_a}
【裁判 B】：{case_b}
核心比對主題/領域：【{topic or '法律爭點橫向對比'}】

{ctx_a}
{ctx_b}

請以結構分明之 Markdown 產出專業比對報告，務必包含以下各大區塊：

### ⚖️ 兩大裁判核心對照綜整矩陣
請使用 Markdown 表格，精準對比以下維度：
| 比對維度 | 🏛️ 【裁判 A】({case_a}) | 🏛️ 【裁判 B】({case_b}) |
| :--- | :--- | :--- |
| **管轄法院與審級** | ... | ... |
| **裁判結果 / 主文** | ... | ... |
| **核心法律爭點** | ... | ... |
| **關鍵適用法條** | ... | ... |
| **採納之學說/理論** | ... | ... |
| **實務拘束力定位** | （如：現行大法庭定錨裁定 / 歷史判例 / 事實審獨立見解） | ... |

### 一、🔍 案例客觀事實異同剖析 (Fact Differences & Distinguishing)
- 兩案在當事人關係、行為態樣、法律事實細節（如善意/惡意、登記外觀、契約約定條款）之關鍵異同。
- 說明為何兩案看似雷同，卻可能因為特定細微事實而有不同判決走向（案例區別技術）。

### 二、🗣️ 雙方當事人主張與攻防焦點對比
- 【裁判 A】中雙方爭執要點 vs 【裁判 B】中雙方攻防要點。

### 三、⚖️ 法院心證與裁判論理核心對比
- 兩案承審法官/法庭在事實認定、法意探求、法益權衡與價值判斷上的心證差異。

### 四、📚 法律見解核心分歧（肯否兩說 / 見解變遷）
- 剖析兩案所代表的法學思潮與見解分歧：
  - 【裁判 A 代表之法理】：立論基礎、採納學者
  - 【裁判 B 代表之法理】：立論基礎、採納學者
  - 兩者是否存在「見解衝突（肯否兩說）」抑或「不同類型案件之區別對待」？

### 五、📈 司法實務發展趨勢與現行有效見解定錨
- 目前最高法院民刑事大法庭、最高行政法院或憲法法庭之終局立場為何？
- 哪一個裁判代表了目前司法實務的穩健主流通說？

### 六、✍️ 司律二試作答高分策略（事實區別與開標涵攝心法）
- 考生在二試申論題中，若題設事實出現類似情境，應如何：
  1. 俐落開標，並同時引述這兩則指標裁判之案號。
  2. 展現高級的「案例區別 (Distinguishing)」法學論述技術。
  3. 大前提確立與事實涵攝的最佳得分範本。

請以清晰、嚴謹之繁體中文 Markdown 輸出。
"""
        result_md = self._call_model(prompt)
        return {
            "case_a": case_a,
            "case_b": case_b,
            "topic": topic,
            "rec_a": rec_a,
            "rec_b": rec_b,
            "markdown_result": result_md,
            "external_search_urls": {
                f"⚖️ 裁判檢索【{case_a}】": generate_judicial_search_urls(case_a).get("🏛️ 司法院 30 年裁判書全文開放檢索 (全台法院)", ""),
                f"⚖️ 裁判檢索【{case_b}】": generate_judicial_search_urls(case_b).get("🏛️ 司法院 30 年裁判書全文開放檢索 (全台法院)", "")
            }
        }

    def analyze_doctrines_by_issue(
        self,
        issue_topic: str,
        subject: str = "",
        custom_context: str = "",
        benchmark_case: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        爭點各說實務裁判歸納矩陣 (Issue Doctrine Clustering & Precedents Spectrum)：
        輸入具體法律爭點，自本機 1,256+ 裁判庫、大法庭裁定、歷審更迭鏈與部會長篇函釋中，
        自動歸納「甲說、乙說、折衷說」各說核心論理，並精確梳理【哪些判決採何說】與【現行終局定錨見解】！
        """
        # 1. 檢索本地相關裁判
        retrieved_cases = search_local_precedents(
            query=issue_topic,
            subject=subject,
            top_k=15
        )

        # 2. 檢索內建指標裁判全文
        matched_landmarks = []
        try:
            from legal_summarizer_engine import BUILTIN_LANDMARK_DOCS
            tokens = [tok for tok in re.split(r'[\s,，、。]+', issue_topic) if len(tok) >= 2]
            for b in BUILTIN_LANDMARK_DOCS:
                b_text = f"{b.get('title', '')} {b.get('text', '')}"
                if any(tok in b_text for tok in tokens):
                    matched_landmarks.append(b)
        except Exception:
            pass

        # 3. 檢索歷審脈絡定錨庫
        history_contexts = []
        try:
            tokens = [tok for tok in re.split(r'[\s,，、。]+', issue_topic) if len(tok) >= 2]
            for k, h in PRESET_JUDGEMENT_HISTORIES.items():
                h_text = f"{h.get('case_id', '')} {h.get('title', '')} {h.get('topic', '')} {h.get('distinguishing_insight', '')}"
                if any(tok in h_text for tok in tokens):
                    history_contexts.append(h)
        except Exception:
            pass

        # 4. 檢索行政函釋大典
        matched_rulings = []
        try:
            from admin_rulings_engine import get_all_administrative_rulings
            rulings = get_all_administrative_rulings()
            tokens = [tok for tok in re.split(r'[\s,，、。]+', issue_topic) if len(tok) >= 2]
            for r in rulings:
                r_text = f"{r.get('title', '')} {r.get('holding', '')} {r.get('content_analysis', '')} {r.get('exam_point_hint', '')}"
                if any(tok in r_text for tok in tokens):
                    matched_rulings.append(r)
                    if len(matched_rulings) >= 5:
                        break
        except Exception:
            pass

        # 5. 組裝大模型專用研析上下文
        cases_context_list = []
        for c in retrieved_cases[:12]:
            cases_context_list.append(
                f"- 【案號】：{c.get('case_id')} | 審級={c.get('court')} ({c.get('level')})\n"
                f"  案由：{c.get('title')}\n"
                f"  裁判要旨：{c.get('holding')[:280]}\n"
                f"  涉及爭點：{c.get('issue')}\n"
                f"  學說與實務定位：{c.get('scholarly_views')}"
            )
        for b in matched_landmarks[:4]:
            cases_context_list.append(
                f"- 【權威指標裁定/判決】：{b.get('title')} ({b.get('doc_type')})\n"
                f"  裁判內文節錄：{b.get('text')[:350]}"
            )
        for h in history_contexts[:3]:
            cases_context_list.append(
                f"- 【歷審見解分歧與大法庭定錨案】：{h.get('case_id')} ({h.get('topic')})\n"
                f"  分歧與定錨核心：{h.get('distinguishing_insight')}\n"
                f"  二試戰略：{h.get('exam_strategy')}"
            )
        for r in matched_rulings[:3]:
            cases_context_list.append(
                f"- 【中央部會長篇函釋】：{r.get('agency')} {r.get('doc_number')} ({r.get('title')})\n"
                f"  函釋核心要旨：{r.get('holding')[:250]}"
            )

        cases_context_str = "\n\n".join(cases_context_list)
        custom_ctx_block = f"【使用者自訂補充事實/背景】：\n{custom_context.strip()}\n----------------------------------------" if custom_context.strip() else ""

        prompt = f"""
你是一位台灣「司法院前最高法院大法庭研究法官」兼「律師司法官高等考試典試委員長」，精通司法實務見解脈絡與學說各說（甲說、乙說、丙說、折衷說、現行大法庭統一見解）。
現在使用者輸入了一個具體之核心法律爭點：【{issue_topic}】
請根據以下檢索之本機裁判庫、大法庭裁定、歷審更迭鏈與行政函釋，執行權威、深度之【爭點各說實務裁判歸納研析】：精確指出實務學說有哪些見解，以及「哪些具體裁判採何說」！

核心法律爭點：【{issue_topic}】
考科領域：【{subject or '實體法與程序法綜合領域'}】

----------------------------------------
【本機權威裁判庫與歷審脈絡鏈檢索結果】：
{cases_context_str if cases_context_str else '（請本於台灣司法裁判演進全集與歷年大法庭/憲法裁判深入梳理）'}
----------------------------------------
{custom_ctx_block}

請嚴格遵循標準繁體中文 Markdown 格式輸出，具備以下各大必備區塊：

### 📊 一、爭點見解全景對照矩陣 (Doctrine Overview Matrix)
請以 Markdown 表格精準呈現各說立場對比：
| 說法名稱 | 核心論理與大前提 | 現行實務拘束力定位 | 採本說之代表裁判字號清單 (哪些判決採此說) |
| :--- | :--- | :--- | :--- |
| **甲說（如：有權處分說 / 交付移轉說 / 特別法排他說）** | ... | 🌟 現行最高法院大法庭統一定錨說 / 憲法法庭判決 | （明確列出具體字號，如最高法院 108 年度台上大字第 1719 號裁定等） |
| **乙說（如：無權處分說 / 契約合意說 / 請求權競合說）** | ... | ⏳ 歷史舊判例 / 事實審部分裁判 | （明確列出具體字號，如最高法院 98 年度台上字第 76 號等） |
| **丙說（若有：折衷說 / 善意保護說 / 類型化區別說）** | ... | ⚖️ 學界有力說 / 特定事實審例外見解 | （列出裁判字號或代表學者） |

### 🏛️ 二、各說核心論理與「採何說」裁判逐案歸納清單 (Case-by-Case Adoption Mapping)
請逐一深入解析各說法，並列出採該說之所有裁判：
#### 1. 【甲說：...】
- **核心法律大前提與立論根據**：法律文義、體系架構、立法目的與保護之實質法益。
- **採本說之具體裁判清單與判旨摘錄**：
  - 🏛️ **裁判案號 1**：（審級、案由）
    - **案件事實特徵**：...
    - **判決要旨核心引述**：以引號引用經典判旨。
  - 🏛️ **裁判案號 2**：...

#### 2. 【乙說：...】
- **核心法律大前提與反對論點**：舊實務論據、對甲說之批評。
- **採本說之具體裁判清單與判旨摘錄**：
  - 🏛️ **裁判案號 1**：...
  - 🏛️ **裁判案號 2**：...

#### 3. 【丙說/折衷說/修正說（若有）】
- **核心論理與適用邊界**：...
- **採本說之裁判或學說代表**：...

### 🔄 三、案例事實區別關鍵 (Case Distinguishing & Fact Nuances)
- 說明採不同說法的各判決，其案件事實中是否存在細微差別（如：第三人善意或惡意、標的物登記外觀、契約特殊特約、除斥期間計算點），導致法院在事實涵攝上有所不同（案例區別技術）。

### 📈 四、司法實務演進歷程與終局定錨 (Precedent Evolution Timeline)
- 梳理實務見解演變時間軸：
  - **舊判例/早期時期**：早期採取何說？
  - **事實審與最高法院各庭分歧時期**：見解如何分歧？
  - **大法庭終局統一定錨時期**：如何統一見解？哪些舊裁判/判例不再援用？

### ✍️ 五、司律二試上位卷 IRAC 實戰破題範本 (300字考場必備金句)
- **【俐落開標示範（40字）】**
- **【大前提肯否二說論述模板（140字）】**（並列兩說並精確引註案號）
- **【事實涵攝與定錨結論（120字）】**（涵攝大法庭定錨說）

### 📚 六、權威法學教授學說評價與評釋
- 王澤鑑、林山田、黃榮堅、姜世明、陳敏等權威法學名家之支持或批判見解。
"""
        result_md = self._call_model(prompt)
        return {
            "issue_topic": issue_topic,
            "subject": subject,
            "candidate_cases": retrieved_cases,
            "benchmark_case": benchmark_case,
            "markdown_result": result_md,
            "search_urls": generate_judicial_search_urls(issue_topic, subject)
        }

    def generate_case_history_timeline(
        self,
        case_id: str,
        case_text: str = ""
    ) -> Dict[str, Any]:
        """
        司法裁判審級更迭與歷審脈絡鏈 (Judgement History / Instance Pipeline)：
        精準溯源裁判於各級法院之演進歷程：
        1. 一審事實審 (地方法院): 兩造起訴與答辯、事實認定、一審裁判主文。
        2. 二審事實審/上訴審 (高等法院): 二審論理、是否逆轉或變更見解、爭點發酵。
        3. 三審法律審 (最高法院): 上訴第三審法律爭議、違背法令指摘、廢棄發回或自為判決。
        4. 大法庭終局裁定 / 憲法法庭判決: 統一見解、廢棄舊判例之定錨效力。
        5. 歷審見解更迭對比 (Distinguishing & Evolution Matrix)。
        6. 國考二試上位卷 IRAC 開標與作答示範。
        """
        preset_info = get_precedent_history_chain(case_id)
        local_rec = get_precedent_by_id(case_id)

        # 動態歷審案號萃取與爭點實質性檢驗 (若非預設三大指標案例，自動自全文或主文中動態溯源)
        from legal_judgment_analyzer import evaluate_judgment_substance, extract_instance_history, format_instance_evolution_markdown
        source_text_for_history = case_text.strip() or (local_rec.get("full_text", "") if local_rec else "") or (local_rec.get("holding", "") if local_rec else "")
        substance_info = evaluate_judgment_substance(source_text_for_history, title=case_id) if source_text_for_history else None

        if not preset_info and source_text_for_history and substance_info:
            dyn_instances = substance_info.get("extracted_history_instances", [])
            if dyn_instances:
                stages = []
                for inst in dyn_instances:
                    stages.append({
                        "stage": inst.get("role", "歷審審級"),
                        "court": inst.get("court", ""),
                        "case_no": inst.get("case_id", ""),
                        "holding_summary": inst.get("snippet", ""),
                        "ruling": inst.get("action", "審理中")
                    })
                preset_info = {
                    "case_id": case_id,
                    "topic": local_rec.get("title", case_id) if local_rec else case_id,
                    "timeline_stages": stages,
                    "distinguishing_insight": "由裁判書全文自動提取之歷審審級更迭脈絡鏈",
                    "exam_strategy": "重點對比本審判決與原審或更審之實體法理轉折點"
                }

        preset_context = ""
        if preset_info:
            preset_context = f"""
【權威歷審脈絡鏈已知數據】：
- 案號與主題：{preset_info.get('case_id')} ({preset_info.get('topic') or preset_info.get('title')})
- 歷審審級路徑：
"""
            stages = preset_info.get("timeline_stages") or preset_info.get("chain", [])
            for node in stages:
                stg = node.get("stage") or node.get("instance", "")
                c_no = node.get("case_no", "")
                ct = node.get("court", "")
                hold = node.get("holding_summary") or node.get("holding", "")
                rul = node.get("ruling") or node.get("result", "")
                preset_context += f"  * [{stg}] {ct} `{c_no}` - {hold} (結果: {rul})\n"
            insight = preset_info.get("distinguishing_insight") or preset_info.get("distinguishing_points", "")
            preset_context += f"- 審級更迭分歧核心：{insight}\n"
            preset_context += f"- 國考上位卷作答策略：{preset_info.get('exam_strategy')}\n"

        # 爭點實質性提示注入
        substance_note = ""
        if substance_info and not substance_info.get("has_legal_issue", True):
            substance_note = f"""
【重要爭點診斷】：本案經系統爭點檢定為【純程序駁回/例行裁定】（{substance_info.get('discard_reason')}），通篇無實體法理爭鳴。
請在歷審脈絡報告中，特別說明本案之所以為程序駁回之原因，並重點引導使用者查閱承載實體爭點之【原審判決：{substance_info.get('substantive_prior_instance', {}).get('case_id', '原審實體判決')}】！
"""

        local_context = ""
        if local_rec:
            local_context = f"""
【本機資料庫裁判摘要】：
- 案號：{local_rec.get('case_id')} ({local_rec.get('court')} {local_rec.get('level')})
- 爭點領域：{local_rec.get('title')} ({local_rec.get('sub_category')})
- 核心要旨：{local_rec.get('holding')}
- 引用法規：{', '.join(local_rec.get('laws_cited', []))}
- 學說評析：{local_rec.get('scholarly_views')}
- 國考作答提示：{local_rec.get('exam_application_hint')}
"""

        user_text_context = ""
        if case_text.strip():
            user_text_context = f"\n【使用者提供之裁判內容節錄】：\n{case_text.strip()[:6000]}\n"

        prompt = f"""
你是一位台灣「司法院前最高法院研究法官」兼「律師司法官高等考試權威講座名師」，精通台灣民刑事及公法訴訟各級法院審級流轉與見解更迭。
現在請針對以下司法裁判進行【司法裁判審級更迭與歷審脈絡鏈 (Judgement History Pipeline)】的深度剖析：

目標裁判：【{case_id}】

{preset_context}
{local_context}
{user_text_context}
{substance_note}

請嚴謹、精確、體系分明地輸出以下七大結構化區塊：

### 一、🏛️ 裁判基本資訊與定錨位階
- 案件字號、承審法院、所屬程序（民事/刑事/行政/憲法）、裁判時點。
- 本裁判於司法實務體系中的定位（如：最高法院大法庭裁定、憲法法庭判決、最高法院具參考價值裁判）。

### 二、🌿 裁判審級更迭脈絡圖 (Instance Evolution Pipeline)
請以清晰的 ASCII 或 Markdown 流程呈現案件自起訴至終局裁判的審級路徑，例如：
`【一審事實審：臺灣ＯＯ地方法院】 ➔ 【二審事實審：臺灣高等法院（見解是否逆轉）】 ➔ 【三審法律審：最高法院】 ➔ 【大法庭終局定錨 / 憲法法庭】`

### 三、🔍 歷審攻防與論理深度剖析
1. **一審事實審（地方法院）**：
   - 原告/檢察官起訴主張 vs 被告抗辯
   - 一審法院認定之主要事實與判決結論
2. **二審事實審 / 上訴審（高等法院）**：
   - 上訴理由與攻防焦點
   - 二審是否逆轉改判？其法律心證與事實認定之關鍵轉折點為何？
3. **三審法律審（最高法院）**：
   - 上訴第三審之違背法令指摘核心
   - 最高法院各庭間過去見解是否有歧異？發回或自為判決之法理剖析
4. **大法庭終局定錨 / 憲法法庭判決（若屬大法庭或憲判字）**：
   - 為何提案大法庭？本案提案法律問題之精準文字
   - 大法庭終局裁定主文與核心法理
   - 是否廢棄或變更早期特定判例、決議？（明確指明被廢止之判例字號）

### 四、⚖️ 審級更迭與各審級見解對比矩陣 (Distinguishing Table)
請繪製 Markdown 對比表格：
| 審級與法院 | 案號字號 | 裁判結果 | 法律見解與心證核心 | 關鍵轉折 / 歧異點 |
| :--- | :--- | :--- | :--- | :--- |
| 一審事實審 (地院) | ... | ... | ... | ... |
| 二審上訴審 (高院) | ... | ... | ... | ... |
| 三審法律審 (最高院) | ... | ... | ... | ... |
| 大法庭 / 憲法法庭 | ... | ... | ... | ... |

### 五、📚 學說論戰與實務評析
- 學界主流（通說）對本案各審級判決之評價
- 有力學說之批評反思與不同見解

### 六、⚠️ 裁判有效性狀態與引用防禦警示
- 🟢 現行有效主流見解 / 🟡 各庭見解歧異中 / 🔴 舊判例已遭大法庭廢棄（考生切勿援用）
- 在訴訟實戰與國家考試中，如何避免誤用已廢止之舊見解

### 七、✍️ 司律二試上位卷 IRAC 作答示範（開標與審級深度論述心法）
- **開標示範**：如何俐落破題並引述大法庭字號
- **爭點論述**：如何將「歷審爭議演進」作為上位卷加分亮點寫入考卷
- **事實涵攝與結論**：示範具體涵攝事實之得分文句

請直接輸出繁體中文 Markdown 報告，文字必須專業、權威，具備最高司法研究等級！
"""
        response_text = self._call_model(prompt)
        return {
            "case_id": case_id,
            "preset_info": preset_info,
            "local_rec": local_rec,
            "markdown_result": response_text,
            "external_search_urls": generate_judicial_search_urls(case_id)
        }

    def unified_legal_search(
        self,
        query: str,
        subject: str = "全部科目",
        court_categories: Optional[List[str]] = None,
        cause_of_action: str = "",
        opinion: str = "",
        argument: str = "",
        statute_target: str = "",
        case_year: str = "",
        case_word: str = "",
        case_num: str = "",
        time_filter: str = "全部時間 (不限年份)",
        filter_no_legal_issue: bool = True
    ) -> Dict[str, Any]:
        """
        全方位法學統一檢索樞紐：
        多維度即時查詢：
        1. 本地權威判解庫 (1,256 筆裁判/大法庭/憲判字/高院/筆記地院)
        2. 司律核心法條庫 (六法全書關聯條號)
        3. 外部審級脈絡 / 專業法學庫 / 司法院 30 年判決跨庫直連
        4. 審級脈絡時間軸過濾滑桿 (time_filter)
        5. 實體爭點實質性過濾 (filter_no_legal_issue: 排除純程序駁回裁定)
        """
        clean_q = query.strip()
        precedents = search_local_precedents(
            query=clean_q,
            subject=subject,
            top_k=8,
            court_categories=court_categories,
            cause_of_action=cause_of_action,
            opinion=opinion,
            argument=argument,
            statute_target=statute_target,
            case_year=case_year,
            case_word=case_word,
            case_num=case_num,
            time_filter=time_filter,
            filter_no_legal_issue=filter_no_legal_issue
        )

        statute_query = statute_target.strip() or clean_q
        matched_articles = []
        try:
            from six_codes_engine import search_articles
            all_arts = search_articles(statute_query)
            matched_articles = all_arts[:6]
        except Exception:
            pass

        full_terms = [t for t in [clean_q, cause_of_action, opinion, argument, statute_target] if t.strip()]
        search_terms = " ".join(full_terms) if full_terms else clean_q
        ext_urls = generate_judicial_search_urls(search_terms, subject)

        return {
            "query": clean_q,
            "subject": subject,
            "precedents": precedents,
            "articles": matched_articles,
            "external_urls": ext_urls
        }
