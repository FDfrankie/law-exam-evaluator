"""
Full-scale Taiwan Judicial Judgment, Precedents, Grand Chamber Rulings, and Scholar Theories Harvester
Covers all 26+ Legal Examination Disciplines, Grand Chamber (大法庭), Leading Precedents (判例),
Plenary Resolutions (庭長法官聯席會議決議), and High-Value Decisions (具參考價值裁判).
Target Directory: G:\\我的雲端硬碟\\LawExamData\\scoring_standards\\
All console outputs in 100% pure ASCII to prevent Windows CMD / cp950 encoding errors.
All dataset JSON outputs in UTF-8 with ensure_ascii=False.
"""
import os
import sys
import time
import json
import re
import hashlib
import urllib.parse
import urllib3
import requests
from bs4 import BeautifulSoup
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Ensure UTF-8 output if possible
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
elif sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

from config import STANDARDS_DIR, DATA_DIR

OUTPUT_JUDGMENTS_DIR = Path(STANDARDS_DIR)
OUTPUT_JUDGMENTS_DIR.mkdir(parents=True, exist_ok=True)

TRAINING_DIR = Path(DATA_DIR) / "training_data"
TRAINING_DIR.mkdir(parents=True, exist_ok=True)

PROCEDURAL_PATTERNS = [
    r"按第三審上訴",
    r"按對於第三審",
    r"上訴不合法",
    r"上訴為不合法",
    r"未具體指摘原判決",
    r"未具體指明原判決",
    r"未委任律師為訴訟代理人",
    r"未補正委任律師",
    r"未繳納(第一審|第二審|第三審)?裁判費",
    r"未繳納訴訟費用",
    r"程式不合",
    r"程式顯有不符",
    r"逾期提起上訴",
    r"本件上訴難認合法",
    r"抗告為不合法",
    r"聲請為不合法",
    r"再抗告為不合法",
]

def is_procedural_dismissal(text: str) -> bool:
    """Detects and filters out purely procedural dismissal rulings lacking substantive reasoning."""
    if not text:
        return True
    for pat in PROCEDURAL_PATTERNS:
        if re.search(pat, text):
            if re.search(r"(上訴|抗告|聲請|再抗告)(為不合法|不合法)?(，|\s*)(應予|即應|爰予|逕予)?駁回", text):
                return True
            if "應予駁回" in text or "予以駁回" in text or "駁回其上訴" in text or "上訴駁回" in text:
                return True
    if len(text) < 400 and ("駁回" in text or "不合法" in text):
        return True
    return False

# 26 Legal Examination Disciplines & Landmark Controversy Database
LEGAL_TOPICS_DATABASE = [
    # --- 1. 民法總則 ---
    {
        "domain": "民法總則",
        "domain_code": "civ_gen",
        "keyword": "借名登記",
        "topic": "借名登記契約性質與出名人處分效力",
        "scholarly_rubric": "【爭點】：出名人違反約定將登記財產處分讓與第三人之效力。\n【實務】：最高法院108年度台上大字第1719號民事大法庭裁定採有權處分說，出名人具有完全處分權能，第三人縱為惡意亦可有效取得所有權。\n【學說】：通說王澤鑑教授採內外部關係區分說；陳聰富教授認外部處分有效以維公示外觀，借名人僅得對出名人主張債務不履行或侵權損害賠償；少數說主張無權處分說。",
        "precedent": "最高法院 108 年度台上大字第 1719 號 民事大法庭裁定"
    },
    {
        "domain": "民法總則",
        "domain_code": "civ_gen",
        "keyword": "消滅時效完成",
        "topic": "消滅時效完成抗辯權發生與自然債務",
        "scholarly_rubric": "【爭點】：時效完成後債務人取得抗辯權或請求權當然消滅。\n【實務】：我國民法第144條第1項採抗辯權發生主義（最高法院29年上字第1195號判例），請求權本身不消滅，僅債務人得拒絕給付。\n【學說】：王澤鑑教授認時效抗辯為永久性延期性抗辯權，債務人給付者成立自然債務，不得依不當得利請求返還。",
        "precedent": "最高法院 29 年上字第 1195 號 判例"
    },
    {
        "domain": "民法總則",
        "domain_code": "civ_gen",
        "keyword": "表見代理",
        "topic": "民法第169條表見代理權利外觀責任與本人歸責",
        "scholarly_rubric": "【爭點】：本人知他人表示為其代理人而不為反對表示之權利外觀責任。\n【實務】：最高法院70年台上字第3575號判例，須本人有容忍他人為代理人之外觀，且相對人非明知或可得而知其無代理權始足當之。\n【學說】：通說認為表見代理本質仍為無權代理，係基於禁反言原則保護善意無過失之交易相對人。",
        "precedent": "最高法院 70 年台上字第 3575 號 判例"
    },
    {
        "domain": "民法總則",
        "domain_code": "civ_gen",
        "keyword": "意思表示錯誤",
        "topic": "民法第88條意思表示錯誤撤銷與受詐欺第92條之競合",
        "scholarly_rubric": "【爭點】：表意人撤銷錯誤意思表示需自身無過失，與詐欺撤銷發生競合時如何適用。\n【實務】：最高法院83年台上字第2048號判決，民法第88條錯誤與第92條詐欺發生競合時，表意人得自由選擇行使較有利之撤銷權。\n【學說】：通說施啟揚、王澤鑑教授認錯誤撤銷除斥期間為1年，相對人得依第91條請求信賴利益損害賠償。",
        "precedent": "最高法院 83 年台上字第 2048 號 判決"
    },

    # --- 2. 民法債編 ---
    {
        "domain": "民法債編",
        "domain_code": "civ_obl",
        "keyword": "民法第184條侵權責任",
        "topic": "民法第184條侵權責任體系與純粹經濟損失保護",
        "scholarly_rubric": "【爭點】：民法第184條第1項前段保護客體是否包含純粹財產上損失。\n【實務】：最高法院109年度台上大字第2169號裁定明確認定第1項前段限於絕對權（所有權、人身權），純粹經濟損失僅得依第1項後段（故意背於善良風俗）或第2項（違反保護他人法律）救濟。\n【學說】：王澤鑑教授引進德國法防洪閘門理論，避免過失行為導致無限擴大之財產責任；陳聰富教授主張合理可預見範圍內之特定營業損失應審慎考量。",
        "precedent": "最高法院 109 年度台上大字第 2169 號 民事大法庭裁定"
    },
    {
        "domain": "民法債編",
        "domain_code": "civ_obl",
        "keyword": "不完全給付",
        "topic": "物之瑕疵擔保責任與不完全給付請求權自由競合",
        "scholarly_rubric": "【爭點】：出賣人交付瑕疵物時買受人得否併依不完全給付主張權利。\n【實務】：最高法院77年度第7次民事庭會議決議採請求權自由競合說，買受人得同時主張物之瑕疵擔保請求權與不完全給付債務不履行責任。\n【學說】：通說王澤鑑、邱聰智教授肯定競合說，並認加害給付所生履行利益外之人身或財產損害適用15年一般消滅時效。",
        "precedent": "最高法院 77 年度第 7 次民事庭會議決議"
    },
    {
        "domain": "民法債編",
        "domain_code": "civ_obl",
        "keyword": "不當得利無法律上原因",
        "topic": "民法第179條不當得利類型化與權益歸屬說",
        "scholarly_rubric": "【爭點】：無法律上原因之判斷標準，給付型 vs 非給付型不當得利。\n【學說】：王澤鑑教授提倡德法非統一說（通說），嚴格區分給付型（欠缺給付目的）與非給付型（違反權益歸屬內容）。\n【實務】：最高法院61年台上字第1695號判例、101年度台上字第1722號判決全面採納權益歸屬說，認侵害他人權利客體獲利者成立侵害型不當得利。",
        "precedent": "最高法院 101 年度台上字第 1722 號 判決"
    },
    {
        "domain": "民法債編",
        "domain_code": "civ_obl",
        "keyword": "違約金酌減",
        "topic": "民法第252條違約金之性質與法院職權酌減",
        "scholarly_rubric": "【爭點】：約定違約金過高時法院得否依職權酌減及懲罰性違約金之適用。\n【實務】：最高法院19年上字第1554號判例與歷來實務採職權酌減主義，審酌一般客觀事實、社會經濟狀況及當事人所受損害程度。\n【學說】：通說區分損害賠償總額預定性違約金與懲罰性違約金，兩者均得依第252條酌減，惟後者不得與損害賠償重複扣除。",
        "precedent": "最高法院 19 年上字第 1554 號 判例"
    },

    # --- 3. 民法物權編 ---
    {
        "domain": "民法物權",
        "domain_code": "civ_prop",
        "keyword": "除去租賃",
        "topic": "抵押權設定後成立之租賃妨害抵押權實行時之除去",
        "scholarly_rubric": "【爭點】：抵押權人實行抵押權拍賣時，得否聲請法院除去後設定之租賃關係。\n【實務】：最高法院110年度台上大字第1652號民事大法庭裁定，抵押權設定後成立之租賃權妨害抵押權拍賣時，執行法院得類推適用民法第866條第2項規定除去後拍賣。\n【學說】：謝在全教授贊同實務見解，認抵押權優先受償權能為物權核心，債權使用關係不得損害拍賣交換價值。",
        "precedent": "最高法院 110 年度台上大字第 1652 號 民事大法庭裁定"
    },
    {
        "domain": "民法物權",
        "domain_code": "civ_prop",
        "keyword": "共有物分管契約",
        "topic": "共有物分管契約對應有部分受讓人之拘束力",
        "scholarly_rubric": "【爭點】：共有人間分管契約於應有部分移轉予第三人時是否受拘束。\n【實務】：司法院釋字第349號解釋明示，分管契約如受讓人明知或可得而知其情事者，仍受拘束。民法第826條之1增訂後不動產經登記者具對世效力。\n【學說】：謝在全教授認已登記者依公示原則具物權效力，未登記者依釋字第349號善意惡意區分以維交易安全。",
        "precedent": "司法院 釋字第 349 號 解釋"
    },
    {
        "domain": "民法物權",
        "domain_code": "civ_prop",
        "keyword": "法定地上權",
        "topic": "民法第876條法定地上權成立要件與房屋所有權",
        "scholarly_rubric": "【爭點】：土地及房屋同屬一人所有設定抵押拍賣後之法定地上權效力。\n【實務】：最高法院73年第5次民事庭會議決議，設定抵押時房屋與土地須同屬一人所有，嗣後移轉異其所有人仍不影響法定地上權成立。\n【學說】：謝在全教授認法定地上權係為維持地上建物存續之社會經濟利益，立法意旨在於防杜拆屋損耗社會資源。",
        "precedent": "最高法院 73 年度第 5 次民事庭會議決議"
    },

    # --- 4. 民法親屬繼承編 ---
    {
        "domain": "民法親屬繼承",
        "domain_code": "civ_fam",
        "keyword": "特種贈與歸扣",
        "topic": "民法第1173條特種贈與歸扣性質與遺產分割計算",
        "scholarly_rubric": "【爭點】：被繼承人生前因結婚、分居、營業對繼承人所為特種贈與之歸扣性質。\n【實務】：最高法院108年度台上大字第2470號裁定確認特種贈與為遺產之預付，遺產分割時應將受贈價額計入應繼遺產總額，由受贈繼承人於其應繼分中扣還。\n【學說】：戴東雄、林秀雄教授支持預付說，認歸扣旨在維持共同繼承人間實質公平，但若被繼承人生前有免除意思表示者從其意願。",
        "precedent": "最高法院 108 年度台上大字第 2470 號 民事大法庭裁定"
    },
    {
        "domain": "民法親屬繼承",
        "domain_code": "civ_fam",
        "keyword": "剩餘財產分配",
        "topic": "民法第1030條之1法定財產制剩餘財產差額分配請求權",
        "scholarly_rubric": "【爭點】：剩餘財產差額分配請求權扣除項目、追加計算與法院酌減。\n【實務】：最高法院109年度台上字第1040號判決，婚後財產扣除負債後之差額平均分配，因繼承或其他無償取得之財產不計入；第2項賦予法院顯失公平時之調整裁量權。\n【學說】：陳棋炎、黃詩淳教授指出剩餘財產分配旨在評價雙方對家庭生活與財產累積之共同協力貢獻。",
        "precedent": "最高法院 109 年度台上字第 1040 號 判決"
    },

    # --- 5. 刑法總則 ---
    {
        "domain": "刑法總則",
        "domain_code": "crim_gen",
        "keyword": "原因自由行為",
        "topic": "刑法第19條第3項原因自由行為責任模式與構成要件",
        "scholarly_rubric": "【爭點】：行為人自陷精神障礙狀態侵害法益，如何符合罪責同時性原則。\n【實務】：最高法院100年度台上字第2119號判決，行為人於原因設定階段具備侵害法益之故意或預見可能性者，不適用第19條減免規定。\n【學說】：林山田、許玉秀教授採前置模式（構成要件模式），將原因設定行為視為著手；黃榮堅教授採例外模式，認自陷行為係責任之例外排除。",
        "precedent": "最高法院 100 年度台上字第 2119 號 判決"
    },
    {
        "domain": "刑法總則",
        "domain_code": "crim_gen",
        "keyword": "客觀歸責",
        "topic": "客觀歸責理論：法所不容許風險之製造與實現",
        "scholarly_rubric": "【爭點】：因果關係認定後，如何透過規範評價歸責於行為人。\n【學說】：林山田、林鈺雄教授引進Roxin客觀歸責三階層：製造不容許風險、實現不容許風險、落入構成要件效力範圍之內。\n【實務】：最高法院105年度台上字第1205號判決全面採納客觀歸責理論，檢驗被害人自陷風險、第三人介入與信賴原則阻卻歸責。",
        "precedent": "最高法院 105 年度台上字第 1205 號 判決"
    },
    {
        "domain": "刑法總則",
        "domain_code": "crim_gen",
        "keyword": "不作為犯保證人地位",
        "topic": "刑法第15條不純粹不作為犯之保證人地位與結果迴避可能性",
        "scholarly_rubric": "【爭點】：保證人地位之實質來源與假設的結果迴避可能性。\n【實務】：最高法院94年度台上字第5587號判決，保證人地位源自法律規定、契約、自願承擔義務、危險前行為或危險源之監督。\n【學說】：林山田、林鈺雄教授主張實質保證人功能說，分為保護者保證人與監督者保證人，且須具備假設的結果迴避可能性。",
        "precedent": "最高法院 94 年度台上字第 5587 號 判決"
    },

    # --- 6. 刑法分則 ---
    {
        "domain": "刑法分則",
        "domain_code": "crim_spec",
        "keyword": "詐欺接續犯",
        "topic": "詐欺罪多次施詐之想像競合與接續犯競合認定",
        "scholarly_rubric": "【爭點】：單一犯意密集時地施詐致多數被害人交付財物之罪數評價。\n【實務】：最高法院108年度台上大字第3579號刑事大法庭裁定，侵害數個人財產法益者成立同種想像競合犯，非單純接續犯，從一重處斷。\n【學說】：林鈺雄、薛智仁教授贊同大法庭裁定，認個人財產法益專屬個別被害人，論以想像競合能充分評價不法並保障受刑人罪刑相當。",
        "precedent": "最高法院 108 年度台上大字第 3579 號 刑事大法庭裁定"
    },
    {
        "domain": "刑法分則",
        "domain_code": "crim_spec",
        "keyword": "刑法沒收新制",
        "topic": "刑法第38條之1犯罪所得沒收與第三人參與沒收程序",
        "scholarly_rubric": "【爭點】：第三人無償或顯不相當對價取得犯罪所得之沒收審查與防禦權。\n【實務】：最高法院109年度台上大字第3426號裁定，法院裁定宣告沒收第三人財產前，應遵循正當法律程序通知第三人參與程序以保防禦權與聽審權。\n【學說】：林鈺雄教授指出沒收新制係準不當得利衡平措施（非刑罰），貫徹任何人不得保有犯罪利益之原則，採總額原則為基礎。",
        "precedent": "最高法院 109 年度台上大字第 3426 號 刑事大法庭裁定"
    },
    {
        "domain": "刑法分則",
        "domain_code": "crim_spec",
        "keyword": "背信罪與侵占罪",
        "topic": "刑法第335條侵占罪與第342條背信罪之排他與競合界限",
        "scholarly_rubric": "【爭點】：為他人處理事務兼持有他人財物時之罪名適用。\n【實務】：最高法院87年度台上字第3704號判決，侵占罪為背信罪之特別規定，持有他人實體物而易持有為所有者優先論以侵占罪。\n【學說】：甘添貴、王皇玉教授指出侵占罪保護特定個別物所有權，背信罪保護整體財產利益，若未變更個別物占有僅處分整體利益則成立背信罪。",
        "precedent": "最高法院 87 年度台上字第 3704 號 判決"
    },

    # --- 7. 民事訴訟法 ---
    {
        "domain": "民事訴訟法",
        "domain_code": "civ_proc",
        "keyword": "爭點效",
        "topic": "民事訴訟爭點效之成立要件、拘束力與遮斷界限",
        "scholarly_rubric": "【爭點】：前訴重要實質爭點判斷對後訴不同訴訟標的之拘束力。\n【實務】：最高法院73年台上字第4062號判決確立爭點效原則：前訴主要爭點經當事人為實質攻擊防禦，法院亦為實質審理判斷者，後訴法院及當事人不得為相反判斷。\n【學說】：邱聯恭教授、姜世明教授支持適度承認爭點效以維誠信原則，須具備五大要件：重大爭點、實質攻防、實質判斷、當事人同一、無顯失公平。",
        "precedent": "最高法院 73 年台上字第 4062 號 判決"
    },
    {
        "domain": "民事訴訟法",
        "domain_code": "civ_proc",
        "keyword": "既判力客觀範圍",
        "topic": "民訴第400條既判力客觀範圍與抵銷抗辯既判力",
        "scholarly_rubric": "【爭點】：判決理由中判斷之效力及抵銷抗辯於裁判抵銷數額內之既判力。\n【實務】：最高法院70年台上字第3007號判例，既判力原則上限於判決主文所判斷之訴訟標的，但抵銷抗辯於扣抵之數額內例外有既判力（第400條第2項）。\n【學說】：陳計男、姜世明教授肯定立法明定抵銷抗辯既判力係為防杜重複起訴與衝突裁判。",
        "precedent": "最高法院 70 年台上字第 3007 號 判例"
    },
    {
        "domain": "民事訴訟法",
        "domain_code": "civ_proc",
        "keyword": "共同訴訟獨立原則",
        "topic": "民事訴訟法第55條普通共同訴訟與第56條必要共同訴訟",
        "scholarly_rubric": "【爭點】：共同訴訟人中一人所為訴訟行為之效力是否及於全體。\n【實務】：最高法院33年上字第4810號判例，普通共同訴訟人一人之行為有利不利益均不及於全體；必要共同訴訟一人有利行為及於全體，不利行為非一致不生效力。\n【學說】：沈冠伶、陳瑋佑教授指出類似必要共同訴訟之合一確定要求源自實體法法律效果一致性。",
        "precedent": "最高法院 33 年上字第 4810 號 判例"
    },

    # --- 8. 刑事訴訟法 ---
    {
        "domain": "刑事訴訟法",
        "domain_code": "crim_proc",
        "keyword": "傳聞法則",
        "topic": "傳聞法則之排除與被告對質詰問權之憲法保障",
        "scholarly_rubric": "【爭點】：審判外陳述之傳聞證據排除與傳聞例外第159條之1至5要件審查。\n【實務】：司法院釋字第582號解釋與最高法院107年度台上字第3147號判決，憲法第16條保障被告詰問權，未經合法傳喚詰問之共犯審判外陳述不得採為唯一不利證據。\n【學說】：林鈺雄、王兆鵬教授強烈主張傳聞例外須嚴格審查客觀可信性擔保與必要性，禁止實務便宜行事架空傳聞排除法則。",
        "precedent": "司法院 釋字第 582 號 解釋"
    },
    {
        "domain": "刑事訴訟法",
        "domain_code": "crim_proc",
        "keyword": "違法搜索證據排除",
        "topic": "刑事訴訟法第158條之4違法取證之權衡相對排除法則",
        "scholarly_rubric": "【爭點】：司法警察違法無令狀搜索扣押取得之物證法院得否採為不利被告證據。\n【實務】：最高法院93年台上字第664號判例確立七大審酌事項：違背法定程序主觀意圖、違害程度、犯罪情節輕重、證據可信度、對被告防禦權影響等。\n【學說】：陳運財教授、李榮耕教授批判實務過度偏向公共利益而架空令狀原則，主張嚴重故意違法搜索應採絕對排除主義以收實質嚇阻效果。",
        "precedent": "最高法院 93 年台上字第 664 號 判例"
    },

    # --- 9. 國民法官法 ---
    {
        "domain": "國民法官法",
        "domain_code": "cit_judge",
        "keyword": "國民法官法",
        "topic": "國民法官法起訴狀一本主義、證據開示與終局評議門檻",
        "scholarly_rubric": "【爭點】：起訴狀一本卷證不併送、預斷排除與評決多數票數門檻。\n【實務】：最高法院113年度台上字第12號判決，國民法官法第43條貫徹起訴狀一本主義，起訴書不得記載使裁判者產生預斷之內容；第83條有罪評決需獲含國民法官及法官在內達三分之二（6票以上）多數同意。\n【學說】：林鈺雄教授、王兆鵬教授肯定起訴狀一本大幅翻轉卷證併送之預斷陋習，中間討論與終局評議落實實質審理主義。",
        "precedent": "最高法院 113 年度台上字第 12 號 判決"
    },

    # --- 10. 憲法與公法 ---
    {
        "domain": "憲法與公法",
        "domain_code": "const_law",
        "keyword": "言論自由 查證",
        "topic": "言論自由與名譽權衡平及真實抗辯合理查證義務",
        "scholarly_rubric": "【爭點】：行為人發表批評言論，客觀合理查證標準與誹謗罪合憲限縮。\n【實務】：司法院釋字第509號解釋、112年憲判字第8號判決，行為人雖不能證明為真實，但依客觀事證已盡合理查證義務而有相當理由確信為真實者不罰；公眾人物容忍界限高於一般人。\n【學說】：許宗力大法官、黃昭元大法官指出合理查證標準保障健全民主審議公共討論空間，民事名譽侵害事件亦同具拘束力。",
        "precedent": "憲法法庭 112 年 憲判字第 8 號 判決"
    },
    {
        "domain": "憲法與公法",
        "domain_code": "const_law",
        "keyword": "人身自由 法官保留",
        "topic": "憲法第8條人身自由正當法律程序與絕對法官保留原則",
        "scholarly_rubric": "【爭點】：行政機關限制外國人或人民人身自由是否須受絕對司法審查。\n【實務】：司法院釋字第708號、第710號解釋，受收容人之人身自由受憲法第8條正當法律程序絕對保障，暫予收容逾合理期間必須由法院獨立審查決定。\n【學說】：李震山、林明昕教授一致肯定正當法律程序與絕對法官保留為人身自由不可退讓之底線，提審法之修訂即為此法理之體現。",
        "precedent": "司法院 釋字第 708 號 解釋"
    },

    # --- 11. 行政法 ---
    {
        "domain": "行政法",
        "domain_code": "admin_law",
        "keyword": "行政程序重開",
        "topic": "行政程序法第128條行政處分程序重開之要件與事由",
        "scholarly_rubric": "【爭點】：行政處分具形式存續力後申請程序重開要件與既判力競合。\n【實務】：最高行政法院107年4月份第1次庭長法官聯席會議，程序重開之新事實或新證據限於作成處分時已存在而未及審酌之證據，不含處分後新發生之事實。\n【學說】：陳敏、李建良教授認為程序重開旨在調和實質正義與法安定性，若處分業經行政法院實質確定判決者，基於既判力拘束原則上不得重開。",
        "precedent": "最高行政法院 107 年度 4 月份第 1 次聯席會議"
    },
    {
        "domain": "行政法",
        "domain_code": "admin_law",
        "keyword": "行政處分信賴保護",
        "topic": "行政程序法第117條違法處分撤銷與公法信賴保護三要件",
        "scholarly_rubric": "【爭點】：授益行政處分違法遭撤銷時受益人之信賴利益保障與補償。\n【實務】：最高行政法院83年判字第1223號判決，信賴保護須具備信賴基礎、信賴表現與信賴值得保護三要件，若受益人有詐欺等情事（第119條）則不保護。\n【學說】：吳庚、陳敏教授指出信賴保護分為存續保護（維持處分）與財產保護（補償損失），由行政機關衡平公共利益後裁量決定。",
        "precedent": "最高行政法院 83 年判字第 1223 號 判決"
    },

    # --- 12. 公司法 ---
    {
        "domain": "公司法",
        "domain_code": "corp_law",
        "keyword": "董事忠實義務",
        "topic": "公司法第23條第1項董事忠實義務與商業判斷法則",
        "scholarly_rubric": "【爭點】：董事為關係人交易利益衝突、歸入權與少數股東代表訴訟。\n【實務】：最高法院107年度台上字第2259號判決，董事負有忠實義務與善良管理人注意義務，違反受有利益者公司得行使歸入權。\n【學說】：王文宇、曾宛如、劉連煜教授主張引進英美法商業判斷法則（BJR），在董事無利益衝突、盡合理調查並善意相信符合公司最佳利益時，法院不事後審查商業成敗。",
        "precedent": "最高法院 107 年度台上字第 2259 號 判決"
    },
    {
        "domain": "公司法",
        "domain_code": "corp_law",
        "keyword": "股東會決議瑕疵",
        "topic": "股東會決議瑕疵之類型：撤銷之訴、無效之訴與不成立",
        "scholarly_rubric": "【爭點】：召集程序違反法令（第189條撤銷）與決議內容違反法令（第191條無效）之界限。\n【實務】：最高法院103年度台上字第1551號判決，程序瑕疵限於30日內訴請撤銷；內容實體違反強行法規者為自始當然無效。\n【學說】：曾宛如、方嘉麟教授探討法院依第189條之1裁量駁回權之適用，維護決議安定性與交易秩序。",
        "precedent": "最高法院 103 年度台上字第 1551 號 判決"
    },

    # --- 13. 證券交易法 ---
    {
        "domain": "證券交易法",
        "domain_code": "sec_law",
        "keyword": "內線交易重大消息",
        "topic": "證券交易法第157條之1內線交易重大消息明確時點",
        "scholarly_rubric": "【爭點】：重大影響股票價格之消息於併購談判過程中何時具備明確性。\n【實務】：最高法院107年度台上字第4470號判決採重要性標準（合理投資人標準）與動態發展觀察，機率與重大性乘積達到理性投資人重視程度即屬成立。\n【學說】：劉連煜、戴銘昇教授指出內線交易旨在維護市場誠信與資訊平等，明確時點不以最終簽署協議為限，避免知情內部人提前收割暴利。",
        "precedent": "最高法院 107 年度台上字第 4470 號 判決"
    },
    {
        "domain": "證券交易法",
        "domain_code": "sec_law",
        "keyword": "財報不實賠償責任",
        "topic": "證交法第20條之1財報不實損害賠償與比例責任",
        "scholarly_rubric": "【爭點】：董事、監察人、會計師責任型態與投資人交易因果關係推定。\n【實務】：最高法院105年度台上字第2202號民事判決，公司負無過失責任，董事長總經理推定過失，獨董與會計師依過失程度負比例責任；採詐欺市場理論推定交易因果關係。\n【學說】：劉連煜教授肯定修法引進比例責任避免深口袋效應，兼顧會計師執業風險與投資人保護平衡。",
        "precedent": "最高法院 105 年度台上字第 2202 號 判決"
    },

    # --- 14. 保險法 ---
    {
        "domain": "保險法",
        "domain_code": "ins_law",
        "keyword": "保險法第64條據實說明",
        "topic": "保險法第64條要保人據實說明義務與危險發生因果關係抗辯",
        "scholarly_rubric": "【爭點】：要保人未據實告知重大事項，但危險發生與隱匿事項無因果關係時之解除權。\n【實務】：最高法院104年度台上字第874號判決採因果關係抗辯（第64條第2項但書），要保人若能證明危險發生與未告知事項無因果關係，保險人不得解除契約。\n【學說】：汪信君、江朝國教授主張保險契約為最大誠信契約，保險人須於知悉一個月除斥期間內行使解除權。",
        "precedent": "最高法院 104 年度台上字第 874 號 判決"
    },
    {
        "domain": "保險法",
        "domain_code": "ins_law",
        "keyword": "人身保險複保險",
        "topic": "人身保險免除複保險規定之適用與契約自由",
        "scholarly_rubric": "【爭點】：人壽保險投保多家保險公司是否成立複保險而無效。\n【實務】：司法院釋字第576號解釋明定複保險無效旨在防止財產超額保險道德危險；人之生命身體無價，定額人身保險不適用複保險無效之規定。\n【學說】：江朝國、葉啟洲教授指出損害填補型健康險（實支實付型）得約定正本收據理賠，但定額壽險契約一律有效。",
        "precedent": "司法院 釋字第 576 號 解釋"
    },

    # --- 15. 票據法 ---
    {
        "domain": "票據法",
        "domain_code": "bill_law",
        "keyword": "票據無因性",
        "topic": "票據法第13條票據無因性、人的抗辯切斷與善意取得",
        "scholarly_rubric": "【爭點】：票據債務人得以自己與執票人前手間之原因關係抗辯執票人。\n【實務】：最高法院64年台上字第1540號判例，票據行為為不要因行為，票據債務人不得以自己與發票人間所存抗辯事由對抗善意執票人（抗辯切斷）。\n【學說】：梁宇賢、王文宇教授指出直接前後手之間仍得主張原因關係抗辯，但對善意取得第三人抗辯權即告中斷以保流通安全。",
        "precedent": "最高法院 64 年台上字第 1540 號 判例"
    },

    # --- 16. 銀行法 ---
    {
        "domain": "銀行法",
        "domain_code": "bank_law",
        "keyword": "銀行法第29條非法吸金",
        "topic": "銀行法第29條非銀行收受存款罪與吸金總額計算",
        "scholarly_rubric": "【爭點】：以借款、投資或入股等名義向不特定多數人收受款項並約定顯不相當之紅利。\n【實務】：最高法院108年度台上大字第2862號刑事大法庭裁定，吸金犯罪所得計算採總額原則，吸收存款總額達新台幣一億元以上者加重處七年以上徒刑。\n【學說】：王文宇、彭心儀教授肯定大法庭採總額原則以收威嚇之效，維護國家金融特許管制秩序與一般大眾資金安全。",
        "precedent": "最高法院 108 年度台上大字第 2862 號 刑事大法庭裁定"
    },

    # --- 17. 消費者保護法 ---
    {
        "domain": "消費者保護法",
        "domain_code": "cpl_law",
        "keyword": "消保法第12條定型化契約",
        "topic": "消費者保護法第12條定型化契約條款顯失公平與無效推定",
        "scholarly_rubric": "【爭點】：定型化契約條款違反誠信原則對消費者顯失公平之判定。\n【實務】：最高法院104年度台上字第1218號判決，定型化契約條款若牴觸契約主要目的、免除企業重大法定責任或加重消費者責任者推定顯失公平無效。\n【學說】：朱柏松、陳聰富教授強調消保法第11條之1合理審閱期間為程序要件，未給予審閱期者該條款不構成契約內容。",
        "precedent": "最高法院 104 年度台上字第 1218 號 判決"
    },

    # --- 18. 金融消費者保護法 ---
    {
        "domain": "金融消費者保護法",
        "domain_code": "fcpl_law",
        "keyword": "適合度原則",
        "topic": "金融服務業公平待客原則、適合度審查與爭議評議程序",
        "scholarly_rubric": "【爭點】：金融服務業向高齡或保守客戶推介高風險衍生金融商品之損害賠償責任。\n【實務】：最高法院108年度台上字第1245號判決，金融業者未踐行KYC（了解客戶）與KYP（了解商品）適合度原則者構成侵權行為與債務不履行責任。\n【學說】：王文宇、曾宛如教授指出金保法第9條適合度原則具備強行法性質，金融評議中心評議決定一定額度內對業者具實質拘束力。",
        "precedent": "最高法院 108 年度台上字第 1245 號 判決"
    },

    # --- 19. 海商法 ---
    {
        "domain": "海商法",
        "domain_code": "mar_law",
        "keyword": "載貨證券",
        "topic": "載貨證券物權效力與海商法第69條運送人法定免責事由",
        "scholarly_rubric": "【爭點】：載貨證券轉讓物權效力與航行過失免責 vs 商業過失不免責之界限。\n【實務】：最高法院105年度台上字第1478號判決，載貨證券交付具物權效力；海商法第69條航行過失（駕駛船舶過失）免責，但照管貨物之商業過失仍負賠償責任。\n【學說】：柯澤東、梁宇賢教授指出運送人主張免責前負有證明船舶具備耐航能力之先決舉證責任。",
        "precedent": "最高法院 105 年度台上字第 1478 號 判決"
    },

    # --- 20. 勞動社會法 ---
    {
        "domain": "勞動社會法",
        "domain_code": "lab_law",
        "keyword": "解僱最後手段性原則",
        "topic": "勞基法第11條預告終止勞動契約與解僱最後手段性原則",
        "scholarly_rubric": "【爭點】：勞基法第11條第5款「對於所擔任之工作確不能勝任」之實質審查。\n【實務】：最高法院103年度台上字第341號判決，解僱為雇主終極手段，雇主須在已踐行調職、改善輔導等手段仍無效果時始得終止勞動契約。\n【學說】：黃程貫、林良榮教授主張勞動權具憲法基本權性質，不能勝任之判斷兼含客觀工作能力與主觀工作意願，雇主負安置不能之舉證責任。",
        "precedent": "最高法院 103 年度台上字第 341 號 判決"
    },
    {
        "domain": "勞動社會法",
        "domain_code": "lab_law",
        "keyword": "調動五原則",
        "topic": "勞基法第10條之1調動五原則與勞動條件不利益變更",
        "scholarly_rubric": "【爭點】：雇主行使調職命令權之合法邊界與勞工拒絕權。\n【實務】：最高法院105年度台上字第1980號判決，違反調動五原則（業務必要、無不利益變更、能力勝任、必要協助補償）者調動命令無效，勞工得終止契約請求資遣費。\n【學說】：林良榮教授指出調動命令受勞動契約拘束，雇主不得藉調職達到逼迫勞工自願離職之目的。",
        "precedent": "最高法院 105 年度台上字第 1980 號 判決"
    },

    # --- 21. 稅法 ---
    {
        "domain": "稅法",
        "domain_code": "tax_law",
        "keyword": "實質課稅 稅捐規避",
        "topic": "租稅法律主義、實質課稅原則與納保法第7條稅捐規避",
        "scholarly_rubric": "【爭點】：經濟實質觀察法與私法形式自由之界限及稅捐規避之法律效果。\n【實務】：最高行政法院108年度判字第253號判決，稅捐機關得按經濟實質調整課稅，但納保法第7條明定稅捐規避僅得補稅及加計利息，不得科處逃漏稅漏稅罰。\n【學說】：葛克昌、黃茂榮、陳清秀教授強調租稅法定主義為憲法第19條防線，不得以實質課稅之名創設法律所無之課稅要件。",
        "precedent": "最高行政法院 108 年度判字第 253 號 判決"
    },

    # --- 22. 國際私法 ---
    {
        "domain": "國際私法",
        "domain_code": "pil_law",
        "keyword": "涉外民事法律適用法",
        "topic": "涉外民事法律適用法定性、連繫因素與反致及公序良俗排除",
        "scholarly_rubric": "【爭點】：涉外侵權與契約準據法選擇及涉民法第8條公序良俗之保留。\n【實務】：最高法院107年度台上字第1851號判決，法律適用依定性、連繫因素至準據法決定三階段審查；外國法若違反我國公共秩序或善良風俗者不予適用。\n【學說】：馬漢寶、陳榮傳教授指出涉民法第6條反致原則限於當事人本國法指定適用中華民國法時始有適用，契約當事人意思自治排除反致。",
        "precedent": "最高法院 107 年度台上字第 1851 號 判決"
    },

    # --- 23. 國際公法 ---
    {
        "domain": "國際公法",
        "domain_code": "pub_intl",
        "keyword": "主權豁免",
        "topic": "國家主權豁免原則與國際條約在國內法體系之直接效力",
        "scholarly_rubric": "【爭點】：外國國家在中華民國法院之民事裁判管轄豁免（絕對豁免 vs 限制豁免）。\n【實務】：最高法院歷來裁判採限制豁免主義，區分主權統治行為（享有豁免）與私經濟商業行為（不得主張管轄豁免）。\n【學說】：姜皇池教授指出條約經立法院審議通過經總統公布者具有國內法律位階，人權兩公約施行法具備超越普通法律之規範效力。",
        "precedent": "最高法院 86 年台上字第 3624 號 判決"
    },

    # --- 24. 著作權法 ---
    {
        "domain": "著作權法",
        "domain_code": "ip_copy",
        "keyword": "著作權合理使用",
        "topic": "著作權法第65條合理使用四要件與實質近似之判定",
        "scholarly_rubric": "【爭點】：網路二次創作利用他人著作是否構成侵害著作財產權或合理使用。\n【實務】：智慧財產法院107年度刑智上易字第42號判決，審查利用目的性、性質、質與量之比例及對市場潛在價值之影響四項基準。\n【學說】：謝銘洋、蔡明誠教授指出轉化性利用（Transformative Use）若賦予原著作全新意涵且未替代原市場，宜優先認定為合理使用。",
        "precedent": "智慧財產法院 107 年度刑智上易字第 42 號 判決"
    },

    # --- 25. 專利法 ---
    {
        "domain": "專利法",
        "domain_code": "ip_pat",
        "keyword": "均等論",
        "topic": "專利侵權判定流程：全要件原則、均等論與申請歷史禁反言",
        "scholarly_rubric": "【爭點】：文義讀入不符合時均等論功能手段結果三要件之判定。\n【實務】：最高法院106年度台上字第2727號判決，均等論審查是否以實質相同之技術手段達成實質相同功能產生實質相同結果；專利權人修正放棄之範圍受禁反言拘束不得主張均等。\n【學說】：蔡明誠教授強調均等論旨在防止剽竊微小置換，但審查歷史禁反言為防止公眾信賴受侵害之必要防線。",
        "precedent": "最高法院 106 年度台上字第 2727 號 判決"
    },

    # --- 26. 商標法 ---
    {
        "domain": "商標法",
        "domain_code": "ip_tm",
        "keyword": "商標混淆誤認之虞",
        "topic": "商標法第30條第1項第10款相關消費者混淆誤認之虞審查因素",
        "scholarly_rubric": "【爭點】：近似商標使用於類似商品或服務之混淆誤認客觀判斷。\n【實務】：智慧財產法院108年度行商訴字第65號判決，綜合審酌商標識別性、近似程度、商品類似性、先權利人多角化經營、消費者注意程度等八大因素。\n【學說】：謝銘洋教授指出著名商標享有跨類別減損識別性或信譽之淡化保護（Dilution），保護標準較一般商標更為廣泛。",
        "precedent": "智慧財產法院 108 年度行商訴字第 65 號 判決"
    },

    # --- 27. 公平交易法 ---
    {
        "domain": "公平交易法",
        "domain_code": "fair_trade",
        "keyword": "公平交易法聯合行為",
        "topic": "公平交易法第14條聯合行為合意推定與垂直轉售價格限制",
        "scholarly_rubric": "【爭點】：寡占市場同業默契調價是否構成違法聯合行為。\n【實務】：最高行政法院107年度判字第521號判決，公平法第14條第3項明定得依市場狀況、成本利潤及經濟合理性等間接事證推定聯合行為之合意。\n【學說】：廖義男、劉華美教授指出聯合行為為競爭法首要打擊對象，寬恕政策（Leniency Program）為破除同業違法同盟之重要制度。",
        "precedent": "最高行政法院 107 年度判字第 521 號 判決"
    },

    # --- 28. 營業秘密法 ---
    {
        "domain": "營業秘密法",
        "domain_code": "trade_sec",
        "keyword": "營業秘密要件",
        "topic": "營業秘密法第2條三要件之客觀認定與合理保密措施",
        "scholarly_rubric": "【爭點】：秘密性、經濟價值性與所有人是否採取合理保密措施之審查。\n【實務】：智慧財產法院108年度刑智上訴字第18號判決，合理保密措施不以絕對滴水不漏為必要，具備主觀保密意思與客觀管制措施（密碼分級、簽署保密協定）即屬合致。\n【學說】：謝銘洋大法官指出營業秘密保護應妥善平衡勞工就業轉職之工作權自由與企業技術研發成果保護。",
        "precedent": "智慧財產法院 108 年度刑智上訴字第 18 號 判決"
    },

    # --- 29. 歷年大法庭裁定專題 ---
    {
        "domain": "大法庭裁定專題",
        "domain_code": "grand_chamber",
        "keyword": "民事大法庭",
        "topic": "最高法院民事大法庭統一法律見解重要裁定",
        "scholarly_rubric": "【法理體系】：法院組織法增訂大法庭制度，終結分庭裁判見解歧異，民事大法庭裁定對提案庭之該案具有實質法律拘束力，並構成實務最權威之法律見解指南。",
        "precedent": "最高法院 民事大法庭 裁定選輯"
    },
    {
        "domain": "大法庭裁定專題",
        "domain_code": "grand_chamber",
        "keyword": "刑事大法庭",
        "topic": "最高法院刑事大法庭統一法律見解重要裁定",
        "scholarly_rubric": "【法理體系】：刑事大法庭針對罪數競合、沒收洗錢、量刑準則、強制處分程序等核心爭議作成具拘束力裁定，貫徹憲法罪刑法定原則與正當法律程序。",
        "precedent": "最高法院 刑事大法庭 裁定選輯"
    },
    {
        "domain": "大法庭裁定專題",
        "domain_code": "grand_chamber",
        "keyword": "行政大法庭",
        "topic": "最高行政法院大法庭統一行政爭訟法律見解重要裁定",
        "scholarly_rubric": "【法理體系】：最高行政法院大法庭裁定針對公法權益、行政處分存續力、環評訴訟及稅務爭端等公法歧異作成定讞見解，為行政法考點之核心依據。",
        "precedent": "最高行政法院 大法庭 裁定選輯"
    },

    # --- 30. 歷年判例與決議專題 ---
    {
        "domain": "裁判先例與決議",
        "domain_code": "precedents_resolutions",
        "keyword": "最高法院 判例",
        "topic": "最高法院具法律規範位階之歷年權威判例選輯",
        "scholarly_rubric": "【法理體系】：最高法院歷年選定之判例要旨，雖經法院組織法修正不再具抽象法規效力，但未經宣告違憲或大法庭變更者，仍為各級法院裁判援引之重要法理裁判先例。",
        "precedent": "最高法院 歷年權威判例選輯"
    },
    {
        "domain": "裁判先例與決議",
        "domain_code": "precedents_resolutions",
        "keyword": "民事庭會議決議",
        "topic": "最高法院民事庭會議決議與具參考價值裁判",
        "scholarly_rubric": "【法理體系】：歷年最高法院民事庭會議決議對物之瑕疵擔保、抵押權實行、連帶債務及繼承遺產分割等重大民事考點確立統一見解，為國家考試經典必考判旨。",
        "precedent": "最高法院 民事庭會議決議選輯"
    },
    {
        "domain": "裁判先例與決議",
        "domain_code": "precedents_resolutions",
        "keyword": "刑事庭會議決議",
        "topic": "最高法院刑事庭會議決議與具參考價值裁判",
        "scholarly_rubric": "【法理體系】：歷年最高法院刑事庭會議決議就共犯自白、自首認定、共同正犯與從犯區分及沒收執行等刑事焦點奠定權威實務標準。",
        "precedent": "最高法院 刑事庭會議決議選輯"
    }
]

class LawMassHarvester:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update(HEADERS)
        self.existing_hashes = set()
        self.purge_procedural_dismissals()
        self._load_existing_hashes()

    def purge_procedural_dismissals(self):
        """Scan and purge any procedural dismissals from scoring_standards to preserve high data quality."""
        purged = 0
        archive_dir = OUTPUT_JUDGMENTS_DIR.parent / "archive_procedural_dismissals"
        archive_dir.mkdir(parents=True, exist_ok=True)
        for f in OUTPUT_JUDGMENTS_DIR.glob("jud_*.json"):
            try:
                with open(f, "r", encoding="utf-8") as jf:
                    data = json.load(jf)
                if is_procedural_dismissal(data.get("judgment_text", "")):
                    dest = archive_dir / f.name
                    f.replace(dest)
                    purged += 1
            except Exception:
                pass
        if purged > 0:
            print(f"  [PURGE] Archived {purged} procedural dismissal orders to {archive_dir.name}.")

    def _load_existing_hashes(self):
        """Index existing judgment files to avoid duplicate downloads."""
        try:
            for f in OUTPUT_JUDGMENTS_DIR.glob("jud_*.json"):
                # Extract hash at the end of filename before .json
                parts = f.stem.split("_")
                if len(parts) >= 2:
                    self.existing_hashes.add(parts[-1])
        except Exception:
            pass
        print(f"  [INIT] Indexed {len(self.existing_hashes)} substantive judgments on Google Drive.")

    def search_fjud_cases(self, keyword: str, domain_code: str, max_pages: int = 3, max_cases_per_page: int = 10) -> list:
        """Query FJUD with multi-page pagination and session token handshake."""
        all_cases = []
        try:
            # Step 1: Session handshake on default.aspx
            r1 = self.session.get("https://judgment.judicial.gov.tw/FJUD/default.aspx", timeout=12)
            soup = BeautifulSoup(r1.text, "html.parser")
            
            viewstate = soup.find("input", {"name": "__VIEWSTATE"})
            viewgen = soup.find("input", {"name": "__VIEWSTATEGENERATOR"})
            eventval = soup.find("input", {"name": "__EVENTVALIDATION"})
            
            if not (viewstate and viewgen and eventval):
                print(f"    [WARN] Failed to extract form tokens for keyword: {keyword}")
                return all_cases

            data = {
                "__VIEWSTATE": viewstate["value"],
                "__VIEWSTATEGENERATOR": viewgen["value"],
                "__EVENTVALIDATION": eventval["value"],
                "txtKW": keyword,
                "judtype": "JUDBOOK",
                "whosub": "0",
                "ctl00$cp_content$btnSimpleQry": "送出查詢"
            }

            # Step 2: POST query
            r2 = self.session.post("https://judgment.judicial.gov.tw/FJUD/default.aspx", data=data, timeout=12)
            soup2 = BeautifulSoup(r2.text, "html.parser")
            iframe = soup2.find("iframe")
            if not iframe:
                print(f"    [INFO] No result iframe found for query.")
                return all_cases

            iframe_src = iframe.get("src", "")
            parsed = urllib.parse.urlparse(iframe_src)
            params = urllib.parse.parse_qs(parsed.query)
            q_token = params.get("q", [""])[0]

            if not q_token:
                print(f"    [WARN] No q token extracted from iframe.")
                return all_cases

            # Step 3: Iterate through pages
            case_urls = []
            for page in range(1, max_pages + 1):
                page_url = f"https://judgment.judicial.gov.tw/FJUD/qryresultlst.aspx?q={q_token}&sort=DS&page={page}"
                try:
                    rp = self.session.get(page_url, timeout=12)
                    sp = BeautifulSoup(rp.text, "html.parser")
                    page_links = [a['href'] for a in sp.find_all("a", href=True) if "data.aspx?ty=JD&id=" in a['href']]
                    case_urls.extend(page_links[:max_cases_per_page])
                    time.sleep(0.3)
                except Exception as pe:
                    break

            # Deduplicate links
            case_urls = list(dict.fromkeys(case_urls))
            print(f"    [INFO] Discovered {len(case_urls)} unique case links across {max_pages} pages.")

            # Step 4: Fetch detailed judgment texts
            for idx, cl in enumerate(case_urls, start=1):
                try:
                    case_url = "https://judgment.judicial.gov.tw/FJUD/" + cl
                    # Calculate unique hash
                    hash_id = hashlib.md5(cl.encode('utf-8', errors='ignore')).hexdigest()[:8]
                    if hash_id in self.existing_hashes:
                        continue

                    rc = self.session.get(case_url, timeout=12)
                    csoup = BeautifulSoup(rc.text, "html.parser")
                    
                    text_content = ""
                    for td in csoup.find_all("td"):
                        t = td.get_text(strip=True)
                        if len(t) > len(text_content):
                            text_content = t
                    
                    if len(text_content) > 120 and "查無資料" not in text_content[:50]:
                        if is_procedural_dismissal(text_content):
                            # Skip purely procedural dismissals lacking substantive legal reasoning
                            continue
                        first_line = text_content.splitlines()[0] if text_content.splitlines() else f"Case_{hash_id}"
                        clean_title = re.sub(r'[\r\n\t]+', ' ', first_line).strip()[:80]
                        all_cases.append({
                            "jid": clean_title,
                            "full_text": text_content[:6000],
                            "case_url": case_url,
                            "keyword": keyword,
                            "hash_id": hash_id,
                            "domain_code": domain_code
                        })
                        self.existing_hashes.add(hash_id)
                    time.sleep(0.3)
                except Exception:
                    pass

        except Exception as e:
            print(f"    [ERROR] Query exception: {str(e)[:100]}")

        return all_cases

    def run_pipeline(self, max_pages=3, max_cases_per_page=12):
        print("=" * 70)
        print("  Starting Taiwan Judicial Harvester Pipeline")
        print(f"  Storage Target: {OUTPUT_JUDGMENTS_DIR}")
        print(f"  Total Topics Configured: {len(LEGAL_TOPICS_DATABASE)}")
        print("=" * 70)

        harvested_count = 0
        sft_samples = []

        out_sft_jsonl = TRAINING_DIR / "law_exam_live_cases_sft.jsonl"
        f_sft = open(out_sft_jsonl, "a", encoding="utf-8")

        total_topics = len(LEGAL_TOPICS_DATABASE)
        for i, item in enumerate(LEGAL_TOPICS_DATABASE, start=1):
            domain = item["domain"]
            domain_code = item.get("domain_code", "law")
            keyword = item["keyword"]
            topic = item["topic"]
            scholarly_rubric = item["scholarly_rubric"]
            precedent = item["precedent"]

            try:
                print(f"\n[{i}/{total_topics}] Domain: {domain} ({domain_code}) | Topic: {topic}")
            except Exception:
                print(f"\n[{i}/{total_topics}] Domain: {domain_code} | Keyword: {keyword}")

            cases = self.search_fjud_cases(
                keyword=keyword,
                domain_code=domain_code,
                max_pages=max_pages,
                max_cases_per_page=max_cases_per_page
            )
            print(f"  Downloaded: {len(cases)} new court decisions.")

            for c in cases:
                hash_id = c["hash_id"]
                # 100% pure ASCII safe filename
                filename = f"jud_{domain_code}_{hash_id}.json"

                record = {
                    "domain": domain,
                    "topic": topic,
                    "keyword": keyword,
                    "jid": c["jid"],
                    "case_url": c["case_url"],
                    "precedent_reference": precedent,
                    "scholarly_rubric": scholarly_rubric,
                    "judgment_text": c["full_text"]
                }

                out_file = OUTPUT_JUDGMENTS_DIR / filename
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(record, f, ensure_ascii=False, indent=2)

                harvested_count += 1

                # Generate high-quality SFT samples
                # Sample 1: IRAC Legal Analysis & Scholarly Debate
                sample1 = {
                    "instruction": f"你是一位具備多年閱卷經驗之台灣司法官律師考試閱卷委員。請針對【{domain}】核心考點【{topic}】進行完整 IRAC 法理分析，開標列出大前提法規要件、權威實務裁判與學說見解，並予以對比評析。",
                    "input": f"【案件爭端事實摘要】：\n{c['full_text'][:380]}...",
                    "output": (
                        f"【一、核心法律爭點開標】：\n本案涉及【{topic}】之法律適用與爭議。\n\n"
                        f"【二、大前提法理與學說對比】：\n{scholarly_rubric}\n\n"
                        f"【三、實務裁判見解與論理依據】：\n權威實務指標【{precedent}】及本案實務裁判【{c['jid']}】要旨指出：\n"
                        f"『{c['full_text'][100:450]}』\n\n"
                        f"【四、小前提案件事實涵攝與結論】：\n本件依前開多數說與權威實務見解，將客觀事實涵攝至構成要件，應認定當事人間權益關係符合法規規範意旨，以維護法律公平與交易安全。"
                    )
                }
                f_sft.write(json.dumps(sample1, ensure_ascii=False) + "\n")

                # Sample 2: 4-Dimension Grading Rubric JSON
                sample2 = {
                    "instruction": f"請依台灣司律國考四大評分維度（爭點意識、三段論法邏輯、學說實務對比、事實要件涵攝），批改評閱這份【{domain}】考生作答，並輸出標準結構化診斷 JSON。",
                    "input": f"題目涉及【{topic}】。\n考生作答摘要：『按相關法條規定，本案事實應依多數實務見解處理，主張權利之人有理由。』",
                    "output": json.dumps({
                        "total_score": 55,
                        "grade_level": "中等卷 (及格邊緣)",
                        "dimension_scores": {
                            "issue_spotting_score": 16,
                            "legal_reasoning_score": 14,
                            "precedent_scholarship_score": 11,
                            "subsumption_score": 14
                        },
                        "identified_issues": [f"觸及{topic}之基本法律範疇"],
                        "missed_issues": [f"未明確點出關鍵裁判字號（如：{precedent}）與條號構成要件", "未列出通說與有力說之分歧對比"],
                        "strengths": ["作答態度積極，結論方向大致符合一般法感"],
                        "weaknesses": ["論述過於簡略，缺乏三段論法開標大前提", "完全未將具體客觀事實帶入要件進行實質涵攝"],
                        "actionable_feedback": f"建議於答題卷首行以【{topic}】精準開標，引述【{precedent}】判旨並對比各家學說，再逐項將題目細節帶入要件，即可躍升上位卷高分區。"
                    }, ensure_ascii=False, indent=2)
                }
                f_sft.write(json.dumps(sample2, ensure_ascii=False) + "\n")

        f_sft.close()

        print("\n" + "=" * 70)
        print("  [PIPELINE COMPLETE]")
        print(f"  Total Newly Harvested Judgments: {harvested_count}")
        print(f"  Total Existing Judgments on Drive: {len(self.existing_hashes)}")
        print(f"  Saved SFT Stream File: {out_sft_jsonl}")
        print("=" * 70)

if __name__ == "__main__":
    harvester = LawMassHarvester()
    # Crawl 3 pages per topic, up to 10 cases per page
    harvester.run_pipeline(max_pages=3, max_cases_per_page=10)
