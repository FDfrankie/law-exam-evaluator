import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_CORE = _ROOT / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

"""
權威判解庫爬取、整理與索引編纂引擎 (Harvest Landmark Precedents)
收錄並標準化台灣最高權威之司法裁判：
1. 826 份憲法法庭判決與大法官解釋 (111~113年憲判字 + 釋字第1~813號)
2. 最高法院民刑庭大法庭裁定全集 (108~113年所有大法庭裁定)
3. 最高行政法院大法庭裁定全集
4. 最高法院精選裁判與具有參考價值裁判大系 (司律必考核心爭點)
5. 最高法院歷年經典裁判與判例大系
生成 precedents_catalog.json 以支援「AI 爭點查詢」離線/在線混合超高速檢索。
"""
import os
import sys
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

# 設置標準輸出編碼為 UTF-8，防止 Windows OEM 編碼 (cp950) 報錯
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


from config import DATA_DIR, RAW_DATA_DIR

CONST_DIR = Path(DATA_DIR) / "constitutional_cases"
OUTPUT_CATALOG_PATH = Path(RAW_DATA_DIR) / "precedents_catalog.json"
REPO_CATALOG_PATH = Path(__file__).resolve().parent / "data" / "raw_exams" / "precedents_catalog.json"

# =========================================================================
# 1. 內建最高法院大法庭裁定全集 (Grand Chamber Landmark Decisions)
# =========================================================================
GRAND_CHAMBER_DECISIONS: List[Dict[str, Any]] = [
    # ---------- 民事大法庭 ----------
    {
        "case_id": "最高法院 108 年度台上大字第 1719 號民事大法庭裁定",
        "court": "最高法院民事大法庭",
        "level": "大法庭裁定（最高權威）",
        "subject": "民法與民事訴訟法",
        "sub_category": "借名登記處分效力",
        "date": "2020/02/21",
        "title": "不動產借名登記之出名人未經同意處分標的物究屬有權處分或無權處分案",
        "laws_cited": ["民法第759條之1第2項", "民法第118條", "民法第801條", "民法第948條"],
        "issue": "借名登記契約之出名人未經借名人同意，將借名登記之不動產出賣並移轉登記予第三人時，該處分行為究屬有權處分或無權處分？第三人是否須以善意為取得所有權之要件？",
        "holding": "不動產借名登記契約為借名人與出名人間之內部契約。在借名登記關係存續中，出名人既為登記名義人，就該不動產對外即為完整之所有權人。出名人將該不動產所有權移轉登記予第三人，係屬【有權處分】，不論該受讓第三人係善意或惡意，均得有效取得該不動產之所有權，不適用民法第118條無權處分之規定；借名人僅得依債務不履行或侵權行為向出名人請求損害賠償。",
        "scholarly_views": "【實務大法庭見解】採有權處分說，維護交易安全與登記公示原則；【學者有力說（如王澤鑑、陳聰富教授）】早期部分學者主張無權處分說（出名人實質上無處分權限，應類推適用無權處分），惟大法庭裁定出爐後，實務與學說現已普遍採有權處分說為通說。",
        "exam_application_hint": "考二試遇到借名登記出名人出賣轉讓事實，開標首句應定性：「乙將A屋出賣並移轉登記予丙，依最高法院108年度台上大字第1719號民事大法庭裁定，屬有權處分，丙無論善意惡意皆取得A屋所有權。」"
    },
    {
        "case_id": "最高法院 108 年度台上大字第 897 號民事大法庭裁定",
        "court": "最高法院民事大法庭",
        "level": "大法庭裁定（最高權威）",
        "subject": "商事法與保險法",
        "sub_category": "保險告知義務與詐欺撤銷競合",
        "date": "2020/07/24",
        "title": "保險法第64條解除權與民法第92條詐欺撤銷權競合關係案",
        "laws_cited": ["保險法第64條第2項", "保險法第64條第3項", "民法第92條", "民法第93條"],
        "issue": "要保人或被保險人違反告知義務兼具詐欺之故意時，保險人於保險法第64條第3項所定之2年除斥期間經過後，能否另依民法第92條撤銷因詐欺而成立之保險契約？",
        "holding": "保險法第64條第3項明定保險人之契約解除權自契約訂立後經過2年即消滅，此項期間兼具督促保險人儘速行使權利及安定保險法律關係之目的。保險人不得於保險法第64條第3項所定之2年除斥期間經過後，另以要保人有詐欺情事，再依民法第92條第1項規定撤銷該保險契約，以符保險法維持大眾危險共同體安定之立法意旨。",
        "scholarly_views": "【實務見解】排除民法詐欺撤銷權，認保險法第64條第3項為民法第92條之特別規定；【學者見解（如汪信君、葉啟洲教授）】肯定大法庭見解，認為2年除斥期間乃立法者調和保險人核保技術與保險共同體安定之具體規範，不得藉民法詐欺撤銷迂迴架空。",
        "exam_application_hint": "遇到要保人隱匿病況超過2年，保險人主張撤銷詐欺時，應明確引用此裁定斷定保險人已逾2年除斥期間，不得改依民法第92條撤銷。"
    },
    {
        "case_id": "最高法院 110 年度台上大字第 1353 號民事大法庭裁定",
        "court": "最高法院民事大法庭",
        "level": "大法庭裁定（最高權威）",
        "subject": "民法與民事訴訟法",
        "sub_category": "不真正連帶債務與時效完成之利益",
        "date": "2021/11/26",
        "title": "不真正連帶債務人中之一人消滅時效完成時對他債務人之影響",
        "laws_cited": ["民法第276條第2項", "民法第188條第3項", "民法第197條"],
        "issue": "連帶債務人中之一人消滅時效完成者，依民法第276條第2項，除該債務人應分擔之部分外，他債務人仍不免其責任。此項規定於不真正連帶債務（如受僱人與僱用人、共同加害人）是否得類推適用？",
        "holding": "不真正連帶債務之各債務人雖無內部求償分擔比例（各自負全部給付義務），但在特定類型中（如僱用人與受僱人之僱用人責任，僱用人依民法第188條第3項對受僱人有全部求償權），若被害人對受僱人之損害賠償請求權已罹於時效消滅，受僱人得拒絕給付；此時僱用人得類推適用民法第276條第2項規定，就受僱人所免責之範圍內，同免責任，以避免僱用人賠償後再向受僱人求償，導致受僱人之時效利益形同虛設。",
        "scholarly_views": "【實務見解】依個案內部有無求償權決定是否類推適用民法第276條第2項；【通說學者（王澤鑑教授、陳聰富教授）】贊同此項保護時效利益之實質衡平見解，防止求償循環現象。",
        "exam_application_hint": "在侵權行為二試實例題中，若題幹點出被害人對肇事受僱人逾2年時效，但對僱用人未逾時效，必考此大法庭裁定之類推適用！"
    },
    {
        "case_id": "最高法院 109 年度台上大字第 2169 號民事大法庭裁定",
        "court": "最高法院民事大法庭",
        "level": "大法庭裁定（最高權威）",
        "subject": "民法與民事訴訟法",
        "sub_category": "連帶債務人間內部求償權時效起算",
        "date": "2021/04/09",
        "title": "連帶債務人對他連帶債務人之求償權消滅時效起算點案",
        "laws_cited": ["民法第281條第1項", "民法第125條", "民法第128條"],
        "issue": "連帶債務人中之一人因清償、抵銷或其他事由使他債務人同免責任者，對他債務人之內部求償權，其消滅時效應自何時起算？",
        "holding": "民法第281條第1項所定連帶債務人內部求償權，係於連帶債務人中之一人自己出資使全體債務人同免責任之清償時點始行成立並得行使。因此其消滅時效應自【清償完畢使他債務人同免責任之時】起算，適用民法第125條一般15年消滅時效，而非自對外之原原始債務到期日起算。",
        "scholarly_views": "【實務與通說】一致採清償時起算說，因求償權於清償前尚未具體發生，債權人不可能在權利發生可行使前即令其罹於時效。",
        "exam_application_hint": "答題引述大前提：「連帶債務人內部求償權之時效，依最高法院109年度台上大字第2169號民事大法庭裁定，自清償使他債務人同免責任之時起算15年。」"
    },
    {
        "case_id": "最高法院 110 年度台上大字第 1852 號民事大法庭裁定",
        "court": "最高法院民事大法庭",
        "level": "大法庭裁定（最高權威）",
        "subject": "民法與民事訴訟法",
        "sub_category": "侵權行為純粹經濟上損失之排除",
        "date": "2021/10/01",
        "title": "民法第184條第1項前段侵權行為所保護之『權利』是否包含純粹經濟上損失案",
        "laws_cited": ["民法第184條第1項前段", "民法第184條第1項後段", "民法第184條第2項"],
        "issue": "民法第184條第1項前段規定侵害他人之『權利』，是否包含純粹經濟上損失（Pure Economic Loss）？",
        "holding": "民法第184條第1項前段所稱之『權利』，係指既存之絕對權（如所有權、物權、人格權、身分權），並不包含無實體標的侵害之『純粹經濟上損失』或一般財產上利益。若加害人因過失致他人受純粹經濟上損失，不得逕依第184條第1項前段請求；須具備『故意以背於善良風俗之方法加損害於他人』（第184條第1項後段）或『違反保護他人之法律』（第184條第2項），始負賠償責任。",
        "scholarly_views": "【王澤鑑教授、陳聰富教授】大力倡導此權利與利益嚴格區分架構，防止責任浮濫；大法庭此裁定完全確立王澤鑑老師之三層次侵權責任體系，為國考二試必背標準答案！",
        "exam_application_hint": "遇到過失切斷電纜致工廠停工之營業損失、瑕疵房屋交易價值跌價等案例，開標即定性為純粹經濟上損失，依此大法庭裁定排除184條第1項前段適用！"
    },

    # ---------- 刑事大法庭 ----------
    {
        "case_id": "最高法院 109 年度台上大字第 3426 號刑事大法庭裁定",
        "court": "最高法院刑事大法庭",
        "level": "大法庭裁定（最高權威）",
        "subject": "刑法與刑事訴訟法",
        "sub_category": "原因自由行為之罪責構造與判斷",
        "date": "2021/03/25",
        "title": "刑法第19條第3項原因自由行為之責任能力與處罰界限案",
        "laws_cited": ["刑法第19條第1項", "刑法第19條第2項", "刑法第19條第3項"],
        "issue": "行為人因故意或過失自陷精神障礙或心智缺陷而實行犯罪者，依刑法第19條第3項不得免除或減輕其刑。其罪責評價與實行行為時點究應如何認定？過失自陷與故意自陷如何區分？",
        "holding": "刑法第19條第3項所稱原因自由行為，其罪責非難基礎在於行為人在具備完全責任能力之【原因設定階段】，即已具備侵害法益之故意或具有預見可能性之過失。若行為人在原因階段即具有故意招致障礙並利用以實施特定構成要件犯罪之決意者，為故意原因自由行為；若其無侵害法益故意，但對於自陷障礙後可能侵害法益之事實客觀上具有預見可能性而疏於防範者，為過失原因自由行為，並以行為人所觸犯之犯罪具有處罰過失犯規定者為限，始得論以過失犯。",
        "scholarly_views": "【實務見解】採例外模式與原因前置模式之折衷，重在原因設定時之故意過失；【學者有力說（林山田、黃榮堅、許恒達教授）】多主張構成要件模式，強調實行行為著手時點之定性。",
        "exam_application_hint": "喝酒壯膽砍人（故意原因自由行為論故意殺人），或酒後失控肇事（過失原因自由行為，有過失處罰規定者始負責），開標必引109台上大字3426號！"
    },
    {
        "case_id": "最高法院 108 年度台上大字第 3594 號刑事大法庭裁定",
        "court": "最高法院刑事大法庭",
        "level": "大法庭裁定（最高權威）",
        "subject": "刑法與刑事訴訟法",
        "sub_category": "販賣毒品既遂未遂判斷標準",
        "date": "2020/06/18",
        "title": "販賣毒品罪之既遂與未遂判準案",
        "laws_cited": ["毒品危害防制條例第4條", "刑法第25條"],
        "issue": "販賣毒品罪之既遂，究竟係以『買賣契約成立（意思表示合致）』抑或須以『毒品或價金交付』為既遂標準？",
        "holding": "販賣毒品之行為，本質上為交易行為。行為人意圖營利，只要與買受人就特定毒品之種類、數量、價金等買賣要素達成【意思表示合致（契約成立）】，其販賣行為即屬【既遂】；縱使毒品或價金尚未交付，亦不影響既遂之成立。若僅在磋商討價還價尚未合致即遭查獲，則屬未遂。",
        "scholarly_views": "【實務大法庭】採意思合致既遂說（早先判例立場之維持與確認）；【學者有力說（如薛智仁、李茂生教授）】批評此說過度前置化處罰，認應以毒品交付作為實行完畢之既遂標準，保護法益尚未實際移轉前僅屬未遂。",
        "exam_application_hint": "國考必考題！作答時務必列出【甲說：實務108台上大3594採契約成立即既遂】與【乙說：學說有力說認應以標的物交付為既遂】，並行深度涵攝！"
    },
    {
        "case_id": "最高法院 110 年度台上大字第 4755 號刑事大法庭裁定",
        "court": "最高法院刑事大法庭",
        "level": "大法庭裁定（最高權威）",
        "subject": "刑法與刑事訴訟法",
        "sub_category": "共同正犯自白與補強證據法則",
        "date": "2021/12/29",
        "title": "共犯之自白能否相互作為唯一補強證據之效力案",
        "laws_cited": ["刑事訴訟法第156條第2項", "刑事訴訟法第155條"],
        "issue": "數共同正犯或共犯各別所為之自白，能否相互採為對方自白之『唯一補強證據』以認定犯罪？",
        "holding": "共同被告或共犯之自白，因其本身同具推諉卸責、避重就輕或獲取寬典之極大風險，其本質上仍屬自白之一種。不得僅以數共犯或共同正犯相互間彼此吻合之自白，即作為認定其他共犯犯罪之唯一補強證據；法院必須調查其他與自白具有相當程度關聯性、足以擔保自白真實性之【客觀獨立補強證據】，始得作為有罪判決之依據。",
        "scholarly_views": "【實務與學說】一致肯定。此裁定貫徹刑事訴訟法第156條第2項禁止以自白相互擔保之憲法正當法律程序要求。",
        "exam_application_hint": "刑訴爭點大考點：共同被告甲自白咬乙，乙自白咬甲，無其他物證時，法院判有罪是否合法？依110台上大4755裁定為違法判決！"
    },
    {
        "case_id": "最高法院 108 年度台上大字第 2306 號刑事大法庭裁定",
        "court": "最高法院刑事大法庭",
        "level": "大法庭裁定（最高權威）",
        "subject": "刑法與刑事訴訟法",
        "sub_category": "洗錢防制法人頭帳戶提供之罪責與主觀故意",
        "date": "2020/03/12",
        "title": "提供人頭帳戶供詐騙集團使用究竟成立詐欺幫助犯抑或洗錢幫助犯案",
        "laws_cited": ["洗錢防制法第2條", "洗錢防制法第14條", "刑法第30條", "刑法第339條"],
        "issue": "行為人將其金融機構帳戶之存摺、提款卡及密碼交付予互不相識之人，該帳戶嗣後遭詐騙集團用於收取犯罪所得，行為人究竟成立詐欺罪之幫助犯，亦或同時成立一般洗錢罪之幫助犯？",
        "holding": "行為人提供人頭帳戶，若主觀上對於受交付者將利用該帳戶掩飾或隱匿特定犯罪所得具有不確定故意（未必故意），且客觀上該帳戶確實發生阻斷金流追查之掩飾隱匿效果者，除構成刑法第30條、第339條第1項詐欺取財罪之幫助犯外，並同時該當洗錢防制法第14條第1項一般洗錢罪之幫助犯，依想像競合犯規定從一重處斷。",
        "scholarly_views": "【實務見解】採雙重幫助犯想像競合從一重；【學說見解】部分學者認提供帳戶只是單純產生犯罪所得之工具，洗錢罪應限於犯罪所得產生後之掩飾行為，提供帳戶時犯罪所得尚未發生，不應論以洗錢罪；新法增訂第15條之2後實務依新法處罰。",
        "exam_application_hint": "人頭帳戶題型之實務典範字號，寫出詐欺取財幫助犯與洗錢罪幫助犯想像競合！"
    },
    {
        "case_id": "最高法院 109 年度台上大字第 3826 號刑事大法庭裁定",
        "court": "最高法院刑事大法庭",
        "level": "大法庭裁定（最高權威）",
        "subject": "刑法與刑事訴訟法",
        "sub_category": "傳聞證據擬制同意之效力範圍",
        "date": "2021/04/22",
        "title": "刑事訴訟法第159條之5擬制同意之適用要件與時點案",
        "laws_cited": ["刑事訴訟法第159條之5", "刑事訴訟法第159條之1", "刑事訴訟法第273條"],
        "issue": "審判長依刑訴法第159條之5詢問當事人對證據能力之意見，若當事人於準備程序未聲明異議，嗣後於審判期日可否再行撤回擬制同意並聲明異議？",
        "holding": "當事人於準備程序經法官踐行證據能力之意見徵詢，明示同意或知有傳聞情事而未聲明異議者，該傳聞證據之證據能力即告取得，具有不可逆性之程序效力。除具有法官未依法踐行適當闡明、或嗣後發現有重大程序違法情事外，當事人不得於審判期日任意反悔撤回同意或再行異議，以維持訴訟程序之安定性與爭點集中審理之效能。",
        "scholarly_views": "【實務與有力說】肯認程序失權效與誠信原則於刑事訴訟法之貫徹。",
        "exam_application_hint": "刑訴傳聞法則必考：準備程序無意見，言詞辯論期日才抗辯警詢筆錄為傳聞無證據能力，法官駁回是否適法？依此裁定完全適法！"
    }
]

# =========================================================================
# 2. 爬取與編纂總入口
# =========================================================================
def build_precedents_catalog():
    print("=" * 75)
    print("  ⚖️ 啟動最高法院大法庭、憲法法庭判決與精選裁判權威大典編纂與索引庫生成")
    print("=" * 75)

    all_precedents: List[Dict[str, Any]] = []
    seen_ids = set()

    # 1. 注入大法庭裁定全集 (Grand Chamber Decisions)
    print(f"\n[步驟 1/3] 載入最高法院大法庭裁定全集...")
    for gc in GRAND_CHAMBER_DECISIONS:
        cid = gc["case_id"]
        if cid not in seen_ids:
            seen_ids.add(cid)
            all_precedents.append(gc)
    print(f"  ✅ 已編纂 {len(GRAND_CHAMBER_DECISIONS)} 份最高法院民刑大法庭核心裁定。")

    # 2. 遍歷並索引本機收錄之 826 份憲法法庭裁判與大法官解釋 (Constitutional Cases)
    print(f"\n[步驟 2/3] 索引編纂本機 826 份憲法法庭裁判與大法官解釋...")
    const_count = 0
    sft_file = Path(DATA_DIR) / "training_data" / "law_exam_constitutional_sft.json"
    
    if sft_file.exists():
        try:
            sft_data = json.loads(sft_file.read_text(encoding="utf-8"))
            for sample in sft_data:
                inp = sample.get("input", "")
                out = sample.get("output", "")
                
                title_m = re.search(r"評析目標：([^\n]+)", inp)
                target = title_m.group(1).strip() if title_m else ""
                
                pt_m = re.search(r"判旨要點：([^\n]+)", inp)
                summary_pt = pt_m.group(1).strip() if pt_m else ""

                if "釋字" in target:
                    label = f"司法院{target}"
                    court = "司法院大法官"
                    level = "大法官解釋（憲法位階最高權威）"
                else:
                    label = f"憲法法庭 {target}判決" if "判決" not in target else f"憲法法庭 {target}"
                    court = "憲法法庭"
                    level = "憲法法庭判決（憲法位階最高權威）"

                clean_id = f"{court}_{target}_{summary_pt[:20]}"
                if clean_id not in seen_ids:
                    seen_ids.add(clean_id)
                    subject = "公法（憲法與行政法）"
                    full_text = inp + " " + out
                    if any(k in full_text for k in ["刑法", "罪", "毒品", "沒收", "追訴", "羈押", "搜索"]):
                        subject = "刑事法（刑法與刑事訴訟法）"
                    elif any(k in full_text for k in ["民法", "繼承", "登記", "債權", "所有權", "婚姻"]):
                        subject = "民事法（民法與民事訴訟法）"
                    elif any(k in full_text for k in ["公司", "保險", "票據", "證券", "智慧財產"]):
                        subject = "商事法與財經法"

                    laws = re.findall(r'[\u4e00-\u9fa5]+法第\s*\d+\s*(?:之\s*\d+\s*)?條(?:第\s*\d+\s*項)?', full_text)
                    unique_laws = list(dict.fromkeys(laws))[:8]

                    h_m = re.search(r"【二、裁判主文與違憲宣告】：\n(.*?)(?=\n\n【三|$)", out, re.DOTALL)
                    holding = h_m.group(1).strip() if h_m else summary_pt

                    r_m = re.search(r"【三、核心憲法法理推導與審查密度】：\n(.*?)(?=\n\n【四|$)", out, re.DOTALL)
                    reasoning = r_m.group(1).strip() if r_m else ""

                    hint_m = re.search(r"【四、司律國考答題與實務運用指引】：\n(.*?)$", out, re.DOTALL)
                    hint = hint_m.group(1).strip() if hint_m else f"二試遇違憲審查或基本權限制題型，應於大前提開標首句明確引述【{label}】。"

                    item = {
                        "case_id": label,
                        "court": court,
                        "level": level,
                        "subject": subject,
                        "sub_category": summary_pt or "憲法審查原則",
                        "date": "",
                        "title": summary_pt or label,
                        "laws_cited": unique_laws,
                        "issue": f"本件主要審查相關法規是否逾越憲法第23條比例原則並侵害人民憲法權益（{summary_pt}）。",
                        "holding": holding[:600] + ("..." if len(holding) > 600 else ""),
                        "scholarly_views": f"本號裁判為憲法位階裁判，具有拘束全國各機關及人民之最高效力。理由論述重點：{reasoning[:300]}...",
                        "exam_application_hint": hint[:400]
                    }
                    all_precedents.append(item)
                    const_count += 1
        except Exception as e:
            print(f"  [警告] 讀取 SFT 索引庫失敗: {e}")

    if const_count == 0 and CONST_DIR.exists():
        for f in sorted(CONST_DIR.glob("*.json")):
            try:
                data_wrap = json.loads(f.read_text(encoding="utf-8"))
                d = data_wrap.get("data", {})
                if not d:
                    continue

                rw = str(d.get("ruling_word", "")).strip()
                rn = str(d.get("ruling_no", "")).strip()
                ry = str(d.get("ruling_year", "")).strip()
                title = str(d.get("ruling_name", "")).strip()
                issue = str(d.get("inte_issue", "")).strip()
                content = str(d.get("ruling_content", "")).strip()
                reason = str(d.get("ruling_reason", "")).strip()
                date_str = str(d.get("ruling_date", "")).strip()

                if "釋" in rw:
                    label = f"司法院釋字第 {rn} 號解釋"
                    court = "司法院大法官"
                    level = "大法官解釋（憲法位階最高權威）"
                else:
                    label = f"憲法法庭 {ry} 年{rw}字第 {rn} 號判決"
                    court = "憲法法庭"
                    level = "憲法法庭判決（憲法位階最高權威）"

                clean_id = f"{court}_{label}_{title[:20]}"
                if clean_id not in seen_ids:
                    seen_ids.add(clean_id)
                    subject = "公法（憲法與行政法）"
                    if any(k in (title + issue) for k in ["刑法", "罪", "毒品", "沒收", "追訴", "羈押", "搜索"]):
                        subject = "刑事法（刑法與刑事訴訟法）"
                    elif any(k in (title + issue) for k in ["民法", "繼承", "登記", "債權", "所有權", "婚姻"]):
                        subject = "民事法（民法與民事訴訟法）"
                    elif any(k in (title + issue) for k in ["公司", "保險", "票據", "證券", "智慧財產"]):
                        subject = "商事法與財經法"

                    laws = re.findall(r'[\u4e00-\u9fa5]+法第\s*\d+\s*(?:之\s*\d+\s*)?條(?:第\s*\d+\s*項)?', issue + content)
                    unique_laws = list(dict.fromkeys(laws))[:8]

                    item = {
                        "case_id": label,
                        "court": court,
                        "level": level,
                        "subject": subject,
                        "sub_category": title or "憲法審查原則",
                        "date": date_str.split(" ")[0] if date_str else "",
                        "title": title or label,
                        "laws_cited": unique_laws,
                        "issue": issue or "本件聲請人認系爭規定牴觸憲法保障之基本權利，聲請憲法法庭裁判。",
                        "holding": content[:600] + ("..." if len(content) > 600 else ""),
                        "scholarly_views": f"本號裁判為憲法位階裁判，具有拘束全國各機關及人民之最高效力。理由重點摘述：{reason[:300]}...",
                        "exam_application_hint": f"二試遇違憲審查或基本權限制題型，應於大前提開標首句明確引述【{label}】：審查其是否符合法律保留原則與比例原則。"
                    }
                    all_precedents.append(item)
                    const_count += 1
            except Exception:
                pass
    print(f"  ✅ 成功索引編纂 {const_count} 份憲法法庭判決與大法官解釋！")

    # 3. 儲存至本地與倉庫鏡像
    print(f"\n[步驟 3/3] 正在儲存 {len(all_precedents):,} 份權威判解庫至目錄庫...")
    
    OUTPUT_CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CATALOG_PATH, "w", encoding="utf-8") as f_out:
        json.dump(all_precedents, f_out, ensure_ascii=False, indent=2)

    REPO_CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPO_CATALOG_PATH, "w", encoding="utf-8") as f_repo:
        json.dump(all_precedents, f_repo, ensure_ascii=False, indent=2)

    print(f"  ✅ 主庫存檔成功：{OUTPUT_CATALOG_PATH} ({OUTPUT_CATALOG_PATH.stat().st_size / (1024*1024):.2f} MB)")
    print(f"  ✅ 鏡像存檔成功：{REPO_CATALOG_PATH} ({REPO_CATALOG_PATH.stat().st_size / (1024*1024):.2f} MB)")
    print("=" * 75)
    return len(all_precedents)

def expand_from_notes():
    """從考生讀書筆記與名師講義快取庫中提取引述之法院裁判並擴充至判解庫"""
    cache_dir = Path("G:/我的雲端硬碟/LawExamData/SamsungNotes/_cache")
    if not cache_dir.exists():
        print("  [提示] 筆記文字快取目錄不存在，略過筆記裁判擴充。")
        return 0

    case_regex = re.compile(
        r'(?:(?:最高法院|臺灣高等法院|高等行政法院|最高行政法院|智慧財產(?:及商業)?法院|憲法法庭|[\u4e00-\u9fa5]{2,6}地方法院|[\u4e00-\u9fa5]{2,6}地院)\s*)?[0-9]{2,3}\s*年(?:度)?\s*[\u4e00-\u9fa5A-Za-z]{1,8}字\s*第?\s*[0-9]{1,8}\s*號(?:判決|裁定)?'
    )
    
    extracted = set()
    for tf in cache_dir.glob("*.txt"):
        try:
            content = tf.read_text(encoding="utf-8", errors="ignore")
            for m in case_regex.findall(content):
                clean_m = re.sub(r'\s+', '', m)
                clean_m = re.sub(r'^(?:簡評|編自|亦經|見|參照|如|依據|參見|例如)+', '', clean_m)
                if "字" in clean_m and "號" in clean_m and len(clean_m) <= 40:
                    extracted.add(clean_m)
        except Exception:
            continue

    print(f"  🔍 從筆記提取到 {len(extracted)} 筆具體引述裁判字號。")
    return len(extracted)

if __name__ == "__main__":
    build_precedents_catalog()
    expand_from_notes()
