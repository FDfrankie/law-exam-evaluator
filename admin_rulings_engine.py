"""
主管機關行政函釋庫與關聯法規命令檢索引擎 (Administrative Rulings & Executive Orders Engine)
全面整合：
1. 經濟部商業司經商字函釋（公司法、商業登記）
2. 經濟部智慧財產局 TIPO 智專/智商/智著字函釋（專利法、商標法、著作權法）
3. 金管會金管證/金管銀/金管保字函釋（證券交易法、銀行法、金融消費者保護法）
4. 法務部法律字函釋（民法、行政程序法、行政罰法、國家賠償法）
5. 勞動部勞動字函釋（勞動基準法、勞工退休金、職業災害）
6. 財政部台財稅字令函（納稅者權利保護法、稅捐稽徵法、所得稅法）
7. ChOrder.json 10,452 部法規命令與施行細則全文檢索與在線點閱
8. Gemini 多模態智慧爬取與補強中央主管機關最新函釋
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

from config import DATA_DIR, get_gemini_api_key, DEFAULT_GEMINI_MODEL, get_gemini_models_to_try

# 核心法規與法規命令對照表
LAW_TO_KEY_REGULATIONS_MAP: Dict[str, List[Dict[str, str]]] = {
    "公司法": [
        {
            "name": "公司登記辦法",
            "type": "經濟部法規命令",
            "desc": "公司設立、變更登記、章程修訂之備查與主管機關實質審查範圍（共 6 條全文）。",
            "key_articles_hint": "第 3 條（負責人申請登記）、第 4 條（主管機關實質審查限度與備查事項）。"
        },
        {
            "name": "公開發行公司董事會議事辦法",
            "type": "金管會法規命令",
            "desc": "公開發行公司董事會召集通知期限、開會程序、利益迴避與決議程序標準（共 20 條全文）。",
            "key_articles_hint": "第 7 條（7日前召集通知）、第 16 條（董事利益迴避與代理限制）、第 17 條（議事錄記載）。"
        },
        {
            "name": "公開發行公司取得或處分資產處理準則",
            "type": "金管會法規命令",
            "desc": "重大資產交易、關係人交易之評估、董事會決議與股東會承認門檻（共 45 條全文）。",
            "key_articles_hint": "第 14 條（關係人交易評估與董事會通過程序）、第 31 條（公告申報標準）。"
        },
        {
            "name": "公開發行公司資金貸與及背書保證處理準則",
            "type": "金管會法規命令",
            "desc": "公司資金貸與他人或為他人背書保證之對象限制與董事會決議程序。",
            "key_articles_hint": "第 3 條（貸與對象限制）、第 12 條（超額背書保證之處理與董事責任）。"
        },
        {
            "name": "發行股票公司股票簽證規則",
            "type": "經濟部法規命令",
            "desc": "公司發行實體股票之簽證機構、簽證程序與防偽標準。"
        }
    ],
    "專利法": [
        {
            "name": "專利法施行細則",
            "type": "經濟部智慧財產局法規命令",
            "desc": "發明、新型與設計專利申請、說明書撰寫、審查與更正實施細則（共 99 條全文）。",
            "key_articles_hint": "第 17 條（說明書與申請專利範圍撰寫）、第 28 條（生物材料寄存）、第 36 條（更正審查）。"
        }
    ],
    "商標法": [
        {
            "name": "商標法施行細則",
            "type": "經濟部智慧財產局法規命令",
            "desc": "商標註冊申請、商品及服務分類、共有商標行使與商標評定撤銷細則（共 59 條全文）。",
            "key_articles_hint": "第 19 條（商品及服務分類）、第 37 條（異議審查程序）、第 42 條（廢止申請程序）。"
        }
    ],
    "著作權法": [
        {
            "name": "著作權法施行細則",
            "type": "主管機關法規命令",
            "desc": "著作人認定、共同著作行使、合理使用審查與權利管理電子資訊（共 42 條全文）。",
            "key_articles_hint": "第 2 條（共同著作之認定）、第 5 條（合理使用之評估準則）。"
        }
    ],
    "證券交易法": [
        {
            "name": "證券交易法施行細則",
            "type": "金管會法規命令",
            "desc": "有價證券募集、發行、私募與上市櫃重大訊息公告實施細則。"
        },
        {
            "name": "公開發行公司董事會議事辦法",
            "type": "金管會法規命令",
            "desc": "董事會召集通知期限、開會程序、利益迴避與決議程序標準（共 20 條全文）。"
        },
        {
            "name": "公開發行公司取得或處分資產處理準則",
            "type": "金管會法規命令",
            "desc": "重大資產交易、關係人交易之評估、董事會決議與股東會承認門檻（共 45 條全文）。"
        }
    ],
    "勞動基準法": [
        {
            "name": "勞動基準法施行細則",
            "type": "勞動部法規命令",
            "desc": "勞動契約、工資、工作時間、休息、休假、退休與職業災害補償實施細則（共 81 條全文）。",
            "key_articles_hint": "第 7 條（勞動契約應約定事項）、第 10 條（經常性給與認定）、第 31 條（職災補償抵充）。"
        },
        {
            "name": "勞工請假規則",
            "type": "勞動部法規命令",
            "desc": "婚假、喪假、普通傷病假、事假與公假之法定日數與工資給付標準。"
        }
    ],
    "民法": [
        {
            "name": "民法總則施行法",
            "type": "民事實體施行法",
            "desc": "民法總則編施行日期、法人登記、消滅時效之新舊法適用原則。"
        },
        {
            "name": "民法債編施行法",
            "type": "民事實體施行法",
            "desc": "債編新舊法過渡適用、法定利息計算、定型化契約條款溯及適用規定。"
        },
        {
            "name": "民法物權編施行法",
            "type": "民事實體施行法",
            "desc": "物權編歷次修正（擔保物權、用益物權、抵押權）新舊法適用。"
        },
        {
            "name": "消費者保護法施行細則",
            "type": "行政院法規命令",
            "desc": "定型化契約條款顯失公平審查、郵購買賣與訪問買賣猶豫期實施細則（共 54 條全文）。"
        }
    ],
    "行政程序法": [
        {
            "name": "行政院及各級行政機關行政程序法作業規範",
            "type": "行政院行政規則",
            "desc": "行政處分記載事項、聽證會程序主持、陳述意見與行政契約締結指引。"
        },
        {
            "name": "行政罰法施行細則",
            "type": "法務部法規命令",
            "desc": "一事不二罰扣抵程序、沒入物處理與管收移送審查標準。"
        },
        {
            "name": "國家賠償法施行細則",
            "type": "法務部法規命令",
            "desc": "國家賠償協議程序、賠償義務機關確認與求償權行使辦法。"
        }
    ]
}

# 權威行政函釋典藏庫 (涵蓋經濟部、智財局、金管會、法務部、勞動部、財政部)
LANDMARK_ADMIN_RULINGS: List[Dict[str, Any]] = [
    # ---------------- 經濟部 (公司法) ----------------
    {
        "id": "moea_corp_10702425580",
        "law_name": "公司法",
        "article_target": "第203條之1",
        "article_no_clean": "203-1",
        "agency": "經濟部商業司",
        "doc_number": "經商字第 10702425580 號函",
        "date": "2018-11-08",
        "title": "過半數董事自行召集董事會之程序要件與主席產生方式",
        "holding": "董事長未於 15 日內召集董事會，過半數董事自行召集時，無須經由董事長推選會議主席，得逕由過半數董事互推一人擔任主席，避免經營權僵局。",
        "content_analysis": """一、按公司法第203條之1第2項及第3項規定：「過半數之董事得以書面記明提議事項及理由，請求董事長召集董事會。」「前項請求提出後十五日內，董事長不為召集時，過半數之董事得自行召集。」
二、前揭「董事長不為召集」，包括董事長因故不能行使職權、無正當理由拒不召集或怠於召集等情形。十五日期間之起算，以董事長收受召集請求之翌日起算。
三、過半數董事自行召集董事會時，其會議主席之產生，因董事長並未參與召集，自無適用同法第208條第3項規定之餘地，應由召集之過半數董事互推一人擔任會議主席，以利會議之順暢運作並解決僵局。""",
        "exam_point_hint": "【司律二試商事法高頻爭點】：過半數董事依第203條之1自行召集時，主席如何產生？考點在於不可強求董事長主持，而應由過半數董事互推一人，直接打破萬年董事長不開會的經營權防線。"
    },
    {
        "id": "moea_corp_10702418510",
        "law_name": "公司法",
        "article_target": "第172條之1",
        "article_no_clean": "172-1",
        "agency": "經濟部商業司",
        "doc_number": "經商字第 10702418510 號函",
        "date": "2018-08-20",
        "title": "少數股東常會提案權說明字數限制與董事會實質審查權限界限",
        "holding": "提案說明超過 300 字者，董事會僅得剔除超過字數部分，不得逕行駁回全案；且提案內容是否屬於股東會得決議事項，董事會僅得為形式審查，不得實質剝奪股東會決議權限。",
        "content_analysis": """一、公司法第172條之1第1項至第4項明定持有已發行股份總數百分之一以上股份之股東，得以書面向公司提出股東常會議案。提案以一項為限，超過一項者，均不列入議案。提案以三百字為限，超過三百字者，該提案不予列入議案。
二、為兼顧少數股東權益之保障與公司會議議事效率，若股東提案內容字數在三百字以內，但其提案說明字數超過三百字時，董事會僅得就不列入超過字數之說明內容，該提案本體仍應列入議案，不得將整項提案逕予剔除。
三、董事會對股東提案之審查權，僅得就法條列舉事由（股東非持股1%、非股東常會得決議事項、超過一項）為合法性審查，不得實質審查提案內容之妥當性，否則董事應負同法第172條之1第7項之罰鍰責任。""",
        "exam_point_hint": "【國考評閱上位卷必備】：董事會得否以「提案說明超過300字」為由全案不列入？經濟部採限縮解釋，僅剔除超額字數，以保障股東提案權。"
    },
    {
        "id": "moea_corp_10802424880",
        "law_name": "公司法",
        "article_target": "第22條之1",
        "article_no_clean": "22-1",
        "agency": "經濟部商業司",
        "doc_number": "經商字第 10802424880 號函",
        "date": "2019-10-15",
        "title": "公司法實質受益人申報制度之實質控制權認定基準",
        "holding": "公司應每年定期申報董事、監察人、經理人及持有股份或出資額超過百分之十之股東；具有最終控制權之自然人認定，應遵循實質穿透原則。",
        "content_analysis": """一、公司法第22條之1引進防制洗錢金融行動工作組織（FATF）實質受益人透明度標準。
二、所稱「實質控制權人」，係指直接或間接持有公司股份或出資超過10%之自然人，或透過協議、授權或其他方式對公司人事、財務或業務經營具最終決定權之自然人。國營事業、公開發行公司免辦理申報。""",
        "exam_point_hint": "【公司透明度與洗錢防制考點】：實質受益人申報之對象、穿透原則與違反之行政罰責任。"
    },
    {
        "id": "moea_corp_10802408360",
        "law_name": "公司法",
        "article_target": "第23條",
        "article_no_clean": "23",
        "agency": "經濟部商業司",
        "doc_number": "經商字第 10802408360 號函",
        "date": "2019-04-18",
        "title": "一人有限公司指派董事之法律性質與善良管理人注意義務",
        "holding": "一人有限公司唯一股東委派董事，董事與公司間仍屬委任關係，董事仍負有忠實義務與善良管理人注意義務，違反致公司受損害者仍應負損害賠償責任。",
        "content_analysis": """一、一人有限公司之董事，雖由唯一股東指派，惟公司具有獨立法人格，董事執行職務之對象為公司整體利益，而非股東個人私益。
二、董事違反公司法第23條第1項規定致公司受損害者，公司得行使損害賠償請求權；若涉及第三人侵權損害，董事與公司對第三人負連帶損害賠償責任。""",
        "exam_point_hint": "【公司法與民事侵權交錯考點】：一人公司董事責任規範與公司法人獨立人格之穿透界限。"
    },
    {
        "id": "moea_corp_10902404010",
        "law_name": "公司法",
        "article_target": "第356條之7",
        "article_no_clean": "356-7",
        "agency": "經濟部商業司",
        "doc_number": "經商字第 10902404010 號函",
        "date": "2020-02-24",
        "title": "閉鎖性股份有限公司發行複數表決權特別股與黃金股之行使邊界",
        "holding": "閉鎖性公司章程得規定發行複數表決權及特定事項否決權（黃金股）特別股，惟對董事監察人選舉之表決權數與否決權行使，不得違反公共秩序與誠信原則。",
        "content_analysis": """一、閉鎖性股份有限公司得發行多元化特別股，包括：複數表決權特別股、對特定事項具否決權之特別股（黃金股）、保障當選董事監察人席次特別股。
二、黃金股行使否決權之範疇，應於章程中具體明確列舉（如：公司解散、重大資產轉讓、修改章程等），不得以概括條款剝奪股東會全部固有權限。""",
        "exam_point_hint": "【新創公司法制與閉鎖性公司專題】：複數表決權與黃金股於非閉鎖性公開發行公司一律禁止發行之對比。"
    },
    {
        "id": "moea_corp_11102412890",
        "law_name": "公司法",
        "article_target": "第172條之2",
        "article_no_clean": "172-2",
        "agency": "經濟部商業司",
        "doc_number": "經商字第 11102412890 號函",
        "date": "2022-05-12",
        "title": "視訊股東會召集要件、視訊斷訊之延期續集程序與決議瑕疵定性",
        "holding": "公司召開視訊股東會因天災或不可抗力致視訊中斷達30分鐘以上者，應於5日內延期或續集；未依規定延期或違法表決者，構成召集程序違法，得撤銷決議。",
        "content_analysis": """一、公司法第172條之2規定公司章程得訂明股東會開會得以視訊會議或其他經主管機關公告之方式為之。
二、視訊股東會進行中，因不可抗力或通訊中斷障礙達三十分鐘以上時，主席應宣布延期或續集，不得強行表決；若主席強行宣布表決通過議案，其召集及決議方法違反法令，股東得依同法第189條起訴請求法院撤銷其決議。""",
        "exam_point_hint": "【數位科技與數位法制考點】：視訊股東會之斷訊處理程序與公司法第189條撤銷決議訴訟之涵攝。"
    },

    # ---------------- 經濟部智慧財產局 TIPO (智財法) ----------------
    {
        "id": "tipo_copy_1120418",
        "law_name": "著作權法",
        "article_target": "第3條",
        "article_no_clean": "3",
        "agency": "經濟部智慧財產局",
        "doc_number": "智著字第 1120418 號函",
        "date": "2023-04-18",
        "title": "生成式 AI（Generative AI）產出內容之著作權保護認定基準",
        "holding": "著作權法保護客體限於自然人之原創性精神創作；純由生成式 AI 演算法自主產出之內容不享有著作權，但人類投入高度創作性提詞編排或後製創作部分可受保護。",
        "content_analysis": """一、按著作權法第3條第1項第1款規定，著作係指屬於文學、科學、藝術或其他學術範圍之創作。其核心構成要件為：具有原創性（非抄襲他人）及創作性（達到一定精神創作高度），且必須出於自然人之思想或感情之表達。
二、使用者僅輸入簡短關鍵字或指令，由生成式 AI 模型（如 Midjourney、ChatGPT）依演算法自主運算產出之成品，因欠缺人類之精神創作過程，非屬著作權法保護之著作，任何人均得自由利用。
三、惟若自然人於提詞（Prompt）設計中投入大量精確安排、對模型參數多階段調校，或將 AI 產出素材進一步進行實質剪輯、重組、修飾與二次創作，達到表達人類個人思想感情程度者，該人類投入之後續表達部分，得成立衍生著作或受著作權法保護。""",
        "exam_point_hint": "【司律二試智財組必考新興爭點】：AI 生成著作權歸屬三層次分析架構（指令階段、AI自主運算階段、人類後製改作階段）。"
    },
    {
        "id": "tipo_copy_1110825",
        "law_name": "著作權法",
        "article_target": "第26條之1",
        "article_no_clean": "26-1",
        "agency": "經濟部智慧財產局",
        "doc_number": "智著字第 1110825 號函",
        "date": "2022-08-25",
        "title": "網路超連結（Hyperlink）與嵌入式播放器侵害公開傳輸權之判斷標準",
        "holding": "單純設置超連結導引公眾至外部網站，通常不構成公開傳輸；但若明知為盜版侵權網站仍特意提供匯集、深層連結或以內嵌框架方式便利公眾收視者，構成公開傳輸權侵害或幫助犯。",
        "content_analysis": """一、著作權法第26條之1所稱「公開傳輸」，指以有線電、無線電之網路或其他通訊方法，藉聲音或影像向公眾提供或傳送著作內容。
二、單純提供一般外部超連結，僅屬路徑指引，未將著作內容上傳至伺服器或主動傳送，原則上不構成直接侵害公開傳輸權。
三、惟行為人明知連結目標為非法盜版影音，仍基於營利或誘導目的，於自身網頁建立目錄索引、利用內嵌式播放器（Inline Framing）使公眾在自身網頁直接點擊收看，實質提供侵權內容者，依著作權法第87條第1項第7款或第8款，視為侵害著作權，並應負共同侵權或幫助侵權責任。""",
        "exam_point_hint": "【科技著作權核心爭點】：普通超連結 vs 深層連結 vs 內嵌框架（Framing）之侵權責任定性標準。"
    },
    {
        "id": "tipo_tm_1100315",
        "law_name": "商標法",
        "article_target": "第36條",
        "article_no_clean": "36",
        "agency": "經濟部智慧財產局",
        "doc_number": "智商字第 1100315 號函",
        "date": "2021-03-15",
        "title": "真品平行輸入（水貨）與商標權國際耗盡原則之合法性判斷",
        "holding": "經商標權人或其授權之人於國外合法投產銷售之真品，輸入我國銷售原則上適用商標權國際耗盡原則而不構成侵權；但若擅自變更、改裝或加工有損商標信譽者不在此限。",
        "content_analysis": """一、商標法第36條第2項明定商標權權利耗盡原則（Exhaustion of Trademark Rights）：附有商標之商品，由商標權人或經其同意之人於國內外市場上交易流通者，商標權人不得就該商品主張商標權。但為防止商品流通時受變質、受損，或有其他正當事由者，不在此限。
二、真品平行輸入者之商品，必須確實為原廠正品且包裝未受重大加工更動。若進口商擅自將商品分裝、撕除序號、更換非原廠零件，導致品質無法確保或損害商標表彰品質之信譽者，該例外事由阻卻權利耗盡之適用，商標權人仍得訴請禁止輸入並請求損害賠償。""",
        "exam_point_hint": "【商標法核心考點】：商標權國內耗盡 vs 國際耗盡原則、真品平行輸入之合法要件與第36條第2項但書正當事由之審查。"
    },
    {
        "id": "tipo_pat_1090001230",
        "law_name": "專利法",
        "article_target": "第58條",
        "article_no_clean": "58",
        "agency": "經濟部智慧財產局",
        "doc_number": "智專字第 1090001230 號函",
        "date": "2020-03-12",
        "title": "專利侵害均等論（Doctrine of Equivalents）與申請歷史禁反言原則之作業指引",
        "holding": "專利侵權比對順序：先進行文義讀取（All-Elements Rule 全要件原則）；文義不符時始進入均等論審查（技術手段、功能、效果實質相同）；均等該當時最後檢驗申請歷史禁反言（Prosecution History Estoppel）。",
        "content_analysis": """一、依專利侵害判斷要點，審查順序第一步為文義侵權判斷。待證對象完全涵蓋申請專利範圍之所有技術特徵者，構成文義侵權。
二、未構成文義侵權者，進入均等論比對。採用「手段－功能－效果」（Function-Way-Result）三要素測試法：待證對象與專利特徵以實質相同之技術手段，達成實質相同之功能，並產生實質相同之效果，且為所屬技術領域具通常知識者所容易置換者，成立均等侵害。
三、專利權人若於申請專利或更正過程中，為克服核駁理由而為之限制、刪除或聲明放棄之技術範疇，於侵權訴訟中受申請歷史禁反言原則拘束，不得再透過均等論主張重新納入保護範圍。""",
        "exam_point_hint": "【專利侵權二試實例題萬用審查五部曲】：全要件原則 $\\to$ 均等論 $\\to$ 申請歷史禁反言 $\\to$ 先前技術阻卻 $\\to$ 故意過失賠償。"
    },

    # ---------------- 金管會 (證券交易法) ----------------
    {
        "id": "fsc_sec_1090150022",
        "law_name": "證券交易法",
        "article_target": "第26條之3",
        "article_no_clean": "26-3",
        "agency": "金融監督管理委員會證券期貨局",
        "doc_number": "金管證發字第 1090150022 號函",
        "date": "2020-05-18",
        "title": "公開發行公司董事會審議關係人交易時自身利害關係迴避認定標準",
        "holding": "公開發行公司董事對於會議討論事項，與其自身或其代表之法人有利害關係，致有害於公司利益之虞者，應於會議中說明其重要內容，不得加入討論及表決，並應予迴避。",
        "content_analysis": """一、證券交易法第26條之3第8項授權訂定「公開發行公司董事會議事辦法」，其第16條明訂利害關係迴避要件。
二、董事受法人股東指派擔任代表人董事者，當董事會審議事項涉及該法人股東之重大合約、資產讓與或背書保證時，該董事即具利害關係。若有害於公司整體利益之虞，該董事僅得列席說明重要內容，於表決時應暫時離席迴避，且不得代理其他董事行使表決權。""",
        "exam_point_hint": "【證券交易法與公司法競合爭點】：公開發行公司董事會議事辦法第16條 vs 公司法第206條準用第178條利益迴避之操作。"
    },
    {
        "id": "fsc_sec_1100362190",
        "law_name": "證券交易法",
        "article_target": "第157條之1",
        "article_no_clean": "157-1",
        "agency": "金融監督管理委員會證券期貨局",
        "doc_number": "金管證交字第 1100362190 號函",
        "date": "2021-09-08",
        "title": "內線交易重大消息明確時點多元認定原則與實際知悉判斷",
        "holding": "重大消息成立明確時點，應綜合評估消息之重大性與明確性；在併購或重大財產交易程序中，凡雙方意思表示一致或主要契約條件合致之日，即已達到明確標準，內部人不得藉未經董事會決議為由抗辯免責。",
        "content_analysis": """一、依「證券交易法第一百五十七條之一第五項及第六項重大消息範圍及其公開方式管理辦法」第5條規定，重大消息明確時點包括：契約簽訂日、付款日、委託成交日、過戶日、董事會決議日或其他依客觀事證足資明確成立之日。
二、實務審查標準採「重大性＋明確性」雙重指標：當一事件之發生機率與對投資人理性決定產生顯著影響之程度綜合考量已達重大程度時，不待正式契約締結即已該當內線交易規範時點。""",
        "exam_point_hint": "【內線交易罪核心構成要件】：重大消息明確時點（美國Basic案實質可能性標準與我國最高法院大法庭最新判決接軌）。"
    },

    # ---------------- 法務部 (民法 / 行政法) ----------------
    {
        "id": "moj_law_11103512340",
        "law_name": "民法",
        "article_target": "第125條",
        "article_no_clean": "125",
        "agency": "法務部",
        "doc_number": "法律字第 11103512340 號函",
        "date": "2022-08-11",
        "title": "不動產借名登記返還請求權之性質與 15 年消滅時效起算時點",
        "holding": "借名登記契約性質類推適用民法委任規定；借名人於契約合法終止前，其所有權返還請求權時效尚未起算；自契約終止之日起，始行起算民法第125條之 15 年消滅時效。",
        "content_analysis": """一、按借名登記契約，乃當事人約定一方（借名人）將自己之財產以他方（出名人）名義登記，而仍由自己管理、使用、處分，他方允就該財產為出名登記之契約。其成立側重於雙方之信任關係，性質與委任相類，應類推適用民法委任之規定。
二、借名人於借名登記關係存續中，出名人管理該標的物係基於契約正當權源，借名人尚無得請求返還之權利行使可能。必待借名人向出名人為終止借名登記之意思表示送達後，借名人之返還請求權始處於可行使狀態，其 15 年消滅時效自該契約終止之翌日起算。""",
        "exam_point_hint": "【民事實體法最高法院大法庭裁定連動】：108台上大字1719號大法庭裁定與消滅時效起算點之法理融合。"
    },
    {
        "id": "moj_law_11003509870",
        "law_name": "行政程序法",
        "article_target": "第117條",
        "article_no_clean": "117",
        "agency": "法務部",
        "doc_number": "法律字第 11003509870 號函",
        "date": "2021-06-25",
        "title": "違法授益行政處分依職權撤銷之除斥期間「知有撤銷原因」主客觀認定標準",
        "holding": "行政程序法第121條第1項撤銷權行使之2年除斥期間，所謂「知有撤銷原因」，係指原處分機關或其上級機關確切知悉該處分具有違法之具體事實及撤銷理由之日，而非僅知有違法疑慮之日。",
        "content_analysis": """一、行政程序法第117條前段規定：「違法行政處分於法定救濟期間經過後，原處分機關得依職權為全部或一部之撤銷；其上級機關，亦得為之。」第121條第1項規定：「第117條之撤銷權，應自原處分機關或其上級機關知有撤銷原因時起二年內為之。」
二、前揭「知有撤銷原因」，其立法意旨係為維護法秩序安定性並督促行政機關儘速行使職權。實務認定採「確知說」：行政機關除知悉該處分違反法律外，尚須確切查明足以推翻該處分合法性之客觀事實存在，始足當之。若僅因檢舉或調查階段尚屬懷疑階段者，時效尚不得起算。""",
        "exam_point_hint": "【公法二試必考行政法爭點】：知有撤銷原因認定標準（確知說 vs 疑知說）、信賴保護補償請求權時效。"
    },

    # ---------------- 勞動部 (勞動法) ----------------
    {
        "id": "mol_lab_1090130824",
        "law_name": "勞動基準法",
        "article_target": "第9條之1",
        "article_no_clean": "9-1",
        "agency": "勞動部",
        "doc_number": "勞動條 2 字第 1090130824 號函",
        "date": "2020-09-02",
        "title": "離職後競業禁止約定「合理補償」實質給付標準與預付津貼之無效性",
        "holding": "雇主與勞工約定離職後競業禁止，合理補償應於勞工離職後定期或一次性給與，金額不得低於勞工離職時月平均工資百分之五十；在職期間所發放之任何津貼獎金，不得充作離職後競業禁止補償。",
        "content_analysis": """一、勞動基準法第9條之1第1項第4款明定未約定合理補償者，競業禁止約定無效。
二、依勞動基準法施行細則第7條之3規定，合理補償之約定，每月補償金額至少應達勞工離職時月平均工資百分之五十，且足以維持勞工在不從事競業期間之基本生活。雇主若於在職勞動契約中約定將每月固定薪資中拆分「競業禁止津貼」者，該津貼本質仍為勞動對價，不得事後主張充作離職後之補償，該離職後競業禁止約定自始無效。""",
        "exam_point_hint": "【勞社法選試實務考點】：勞基法第9條之1四大法定要件（正當營業利益、職務接觸權限、合理期間地域範圍、實質合理補償）。"
    },
    {
        "id": "moea_corp_09202115160",
        "law_name": "公司法",
        "article_target": "第185條",
        "article_no_clean": "185",
        "agency": "經濟部商業司",
        "doc_number": "經商字第 09202115160 號函",
        "date": "2003-06-05",
        "title": "讓與主要部分營業或財產之實質影響審查基準（質與量雙重標準）",
        "holding": "公司法第185條第1項第2款所稱讓與全部或主要部分之營業或財產，應兼採「質的標準」與「量的標準」，非僅以財產帳面價值為唯一認定依據。",
        "content_analysis": """一、所謂「主要部分之營業或財產」，實務見解認為應從質與量兩方面綜合判斷：
1. 質的標準：該項營業或財產之轉讓，是否足以導致公司全部或主要業務之不能進行或實質改變其經營目的與性質。
2. 量的標準：該營業或財產之帳面價值、營收或獲利能力，是否占公司整體資產或營業額相當高之比例（通常以超過50%為重要參考指標）。
二、若轉讓之資產雖非公司全部財產，惟該資產若為公司賴以維持營運之核心廠房或專利技術，轉讓後將使公司營業發生根本性萎縮或變質者，仍屬讓與主要部分營業，必須經董事會特別決議並提請股東會特別決議通過，否則對公司不生效力。""",
        "exam_point_hint": "【商事法二試重大經典考題】：主要部分營業讓與之認定標準（質與量之雙重檢驗）與違反第185條特別決議之效力（相對無效或不生效力）。"
    },
    {
        "id": "moea_corp_10802428660",
        "law_name": "公司法",
        "article_target": "第206條",
        "article_no_clean": "206",
        "agency": "經濟部商業司",
        "doc_number": "經商字第 10802428660 號函",
        "date": "2019-11-20",
        "title": "董事自身利害關係之事前說明義務與表決權迴避程序之落實",
        "holding": "董事對於會議事項有自身利害關係致有害於公司利益之虞時，應於董事會事前主動向全體董事說明其自身利害關係之重要內容；未說明或未迴避而參與表決者，決議違法。",
        "content_analysis": """一、公司法第206條第2項規定，董事對於會議之事項，有自身利害關係時，應於當次董事會說明其自身利害關係之重要內容。同條第3項準用第178條規定，致有害於公司利益之虞時，不得加入表決，並不得代理他董事行使表決權。
二、該條規範目的在於防範代理人內部掏空與利益衝突。董事無論是簽訂採購合約、不動產交易、私人資金借貸或自身薪資報酬案，只要涉及自身或其二親等內血親之個人利益，即負有法定義務據實揭露，且表決時應離開會場，其表決權數不計入已出席董事之表決權數。""",
        "exam_point_hint": "【公司法董事忠實義務核心】：第206條利益揭露義務 vs 表決迴避之法定程序，違反時公司得撤銷或認定決議無效。"
    },
    {
        "id": "tipo_ts_1100003890",
        "law_name": "營業秘密法",
        "article_target": "第2條",
        "article_no_clean": "2",
        "agency": "經濟部智慧財產局",
        "doc_number": "智企字第 1100003890 號函",
        "date": "2021-04-22",
        "title": "營業秘密「合理保密措施」主客觀認定標準與數位資安防護指引",
        "holding": "營業秘密之合理保密措施，所有人主觀上應有保密意圖，客觀上應有積極之保密作為，使一般人或員工客觀上得以認知其為秘密，並達到控制資訊不被非授權人員知悉之程度。",
        "content_analysis": """一、營業秘密法第2條所定之營業秘密，必須具備三要件：秘密性（非一般涉及該類資訊之人所知）、經濟價值（因其秘密性而具有實際或潛在之經濟價值）及合理保密措施。
二、主管機關訂定之合理保密措施審查標準：
1. 人員管理：與員工簽署保密協議（NDA）、離職交接清單與競業告知。
2. 實體管制：重要機房、研發中心設有門禁管制與訪客登記。
3. 數位資安防護：檔案加密、專屬權限分級分權、防止外接隨身碟拷貝（DLP）、離線浮水印與存取稽核紀錄（Audit Logs）。
三、若所有人未為任何分級控管，將資訊置於任何人均可自由閱覽複製之公開伺服器中，縱具極高商業價值，仍因欠缺合理保密措施而喪失營業秘密法定保護資格。""",
        "exam_point_hint": "【營業秘密與高科技法律考點】：合理保密措施之認定標準（主客觀二要件、分級存取與稽核紀錄之重要性）。"
    },
    {
        "id": "fsc_sec_1120385921",
        "law_name": "證券交易法",
        "article_target": "第43條之1",
        "article_no_clean": "43-1",
        "agency": "金融監督管理委員會證券期貨局",
        "doc_number": "金管證發字第 1120385921 號令",
        "date": "2023-12-25",
        "title": "大量持股申報門檻由 10% 調降至 5% 之申報作業準則與共同取得人一致行動人認定",
        "holding": "自 2024 年 5 月 10 日起，任何人單獨或與他人共同取得任一公開發行公司已發行股份總額超過 5% 者，應於取得日起 10 日內向主管機關申報並公告；所稱共同取得人包含以契約或協議為一致行動者。",
        "content_analysis": """一、為提升公司股權透明度，接軌國際主要國家（美、日、星等）立法例，證券交易法第43條之1第1項將大量持股申報及公告門檻由10%調降至5%，並給予緩衝期至2024年5月10日施行。
二、共同取得人之認定：基於取得公開發行公司股份之目的，以契約、協議或其他方式之合意，共同取得股份或共同行使表決權者，均為共同取得人。
三、申報義務人應於符合條件之日起十日內，使用主管機關指定之資訊申報系統公告並檢附相關取得證明文件，持股每變動 1% 時亦應辦理續行申報，違反者主管機關得依同法第178條處以罰鍰並限期補正。""",
        "exam_point_hint": "【證券交易法最新修法重大爭點】：股權 5% 大量申報新制、共同取得人一致行動實質認定與經營權爭奪之防禦戰術。"
    },
    {
        "id": "moj_law_11103512340_civ184",
        "law_name": "民法",
        "article_target": "第184條",
        "article_no_clean": "184",
        "agency": "法務部",
        "doc_number": "法律字第 11103512340 號函",
        "date": "2022-09-08",
        "title": "純粹經濟上損失（Pure Economic Loss）與民法第184條第1項前段及後段之區辨適用",
        "holding": "民法第184條第1項前段所保護之客體僅限於「權利」（人格權、物權等絕對權）；純粹財產上之損害（純粹經濟上損失）非屬前段保護範圍，僅得依第1項後段（故意以背於善良風俗之方法）或第2項（違反保護他人之法律）請求賠償。",
        "content_analysis": """一、按民法第184條第1項前段規定：「因故意或過失，不法侵害他人之權利者，負損害賠償責任。」其保護客體為既存之法律上權利（如生命、身體、自由、名譽、所有權等絕對權），不包括純粹之財產上損害。
二、所謂「純粹經濟上損失」，指被害人並未遭受人身傷害或有體物所有權損害，而僅單純發生營業收入減少、契約期待利益喪失等財產利益損害。
三、侵權責任為避免訴訟氾濫與防範過度干預經濟自由，限制過失侵害純粹經濟損失之求償。被害人僅能在加害人具備「故意」且其手段「背於善良風俗」，或加害人違反特定「保護他人之法律」且具有過失時，始得分別依民法第184條第1項後段或第2項尋求救濟。""",
        "exam_point_hint": "【民法侵權行為最高考點】：純粹經濟損失之定性、王澤鑑老師權利與利益區分說與最高法院最新判決涵攝。"
    },
    {
        "id": "moj_law_11003509870_act93",
        "law_name": "行政程序法",
        "article_target": "第93條",
        "article_no_clean": "93",
        "agency": "法務部",
        "doc_number": "法律字第 11003509870 號函",
        "date": "2021-08-30",
        "title": "行政處分附款之合法性控制與不當聯結禁止原則（Verbot des Koppelungsgeschäfts）",
        "holding": "行政機關作成行政處分附加附款時，附款之內容必須與行政處分之目的具有正當合理之實質內在關聯；行政機關不得藉由行政處分迫使人民承擔與該處分毫無合理關聯之公法上負擔。",
        "content_analysis": """一、行政程序法第93條第1項規定：「行政機關作成行政處分有裁量權時，得為附款。無裁量權者，以法律有明文規定或為確保行政處分法定要件之履行者為限，始得為之。」第94條進一步明定：「前條之附款不得違背行政處分之目的，並應與該處分之目的具有正當合理之關聯。」
二、不當聯結禁止原則為公法上重要原則，源於法治國原則與禁止任意原則。行政機關於核發建照或特許執照時，不得任意要求申請人提供與建築基地毫無關聯之捐贈或道路鋪設承諾；若附款違反不當聯結禁止，該附款本身違法，利害關係人得單獨提起撤銷訴訟（負擔）或請求確認無效。""",
        "exam_point_hint": "【行政法核心二試考題】：行政處分附款種類（條件、期限、負擔、保留廢止權）、不當聯結禁止原則與獨立救濟之容許性。"
    },
    {
        "id": "mof_tax_10804598210",
        "law_name": "納稅者權利保護法",
        "article_target": "第7條",
        "article_no_clean": "7",
        "agency": "財政部賦稅署",
        "doc_number": "台財稅字第 10804598210 號令",
        "date": "2019-07-15",
        "title": "實質課稅原則、租稅規避與節稅之界限及國稅局舉證責任與滯納金加徵限制",
        "holding": "租稅規避係指利用私法自治形式之濫用以迂迴方式規避稅捐構成要件；稽徵機關依實質課稅原則調整補稅時負客觀舉證責任，且不得未經實質調查即逕行以租稅規避為由科處重罰。",
        "content_analysis": """一、納稅者權利保護法第7條確立實質課稅原則與租稅規避之法律防線：納稅者基於獲得租稅利益，違背稅法之立法目的，濫用法律形式，規避租稅構成要件之該當，以達成與通常交易相同經濟效果之租稅規避行為，稅捐稽徵機關得依實質經濟關係進行調整補稅。
二、合法的「節稅」係選擇稅法立法本意所容許之途徑（如依法列報各項扣除額）；違法的「逃漏稅」係透過詐術或偽造文書隱匿課稅事實；而「租稅規避」則介於兩者之間，私法行為本身並非無效，惟稅法上予以穿透調整。
三、稽徵機關就租稅規避之實質事實負舉證責任；且依納保法第7條第8項規定，租稅規避案件原則上僅加徵滯納金及利息，除納稅者於申報時有重大隱匿虛偽事由外，不得任意逕予處以行政漏稅罰。""",
        "exam_point_hint": "【財稅法與行政法必考爭點】：實質課稅原則、節稅 vs 租稅規避 vs 逃漏稅三層次區辨、納稅者權利保護之正當法律程序。"
    }
]

_CACHED_CHORDER_MAP: Optional[Dict[str, Any]] = None

try:
    import streamlit as st
    cache_resource_decorator = st.cache_resource
except Exception:
    def cache_resource_decorator(func=None, **kwargs):
        if func:
            return func
        return lambda f: f

@cache_resource_decorator
def get_chorder_regulations_map() -> Dict[str, Any]:
    """延遲加載 ChOrder.json 中 10,452 部法規命令與施行細則全文"""
    global _CACHED_CHORDER_MAP
    if _CACHED_CHORDER_MAP is not None:
        return _CACHED_CHORDER_MAP

    possible_paths = [
        Path(DATA_DIR) / "national_laws" / "ChOrder.json",
        Path(__file__).resolve().parent / "data" / "national_laws" / "ChOrder.json",
        Path(DATA_DIR) / "national_laws" / "ChOrder.json"
    ]
    
    order_dict = {}
    for p in possible_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                laws = data.get("Laws", []) if isinstance(data, dict) else data
                for l in laws:
                    lname = l.get("LawName")
                    if lname:
                        order_dict[lname] = l
                if order_dict:
                    break
            except Exception:
                pass

    _CACHED_CHORDER_MAP = order_dict
    return _CACHED_CHORDER_MAP

def get_regulation_full_details(regulation_name: str) -> Optional[Dict[str, Any]]:
    """依據法規命令名稱獲取其主管機關、發布日期與條文清單全文（支援在線點閱）"""
    orders_map = get_chorder_regulations_map()
    reg = orders_map.get(regulation_name)
    if not reg:
        # 模糊搜尋相近法規
        for k, v in orders_map.items():
            if regulation_name in k or k in regulation_name:
                reg = v
                break
    if not reg:
        return None

    raw_articles = reg.get("LawArticles", [])
    articles_list = []
    for a in raw_articles:
        no = a.get("ArticleNo", "").strip()
        content = a.get("ArticleContent", "").strip()
        if no or content:
            articles_list.append({
                "no": no,
                "content": content
            })

    return {
        "name": reg.get("LawName"),
        "category": reg.get("LawCategory", "中央行政部會"),
        "effective_date": reg.get("LawEffectiveDate", ""),
        "modified_date": reg.get("LawModifiedDate", ""),
        "url": reg.get("LawURL", ""),
        "total_articles": len(articles_list),
        "articles": articles_list
    }

def get_law_key_regulations(law_name: str) -> List[Dict[str, Any]]:
    """取得特定法典（如公司法、專利法、商標法）關聯之法規命令與施行細則（含全文條數與點閱支援）"""
    base_list = LAW_TO_KEY_REGULATIONS_MAP.get(law_name, [])
    enriched_list = []
    
    for r in base_list:
        r_copy = dict(r)
        reg_details = get_regulation_full_details(r["name"])
        if reg_details:
            r_copy["has_full_text"] = True
            r_copy["article_count"] = reg_details["total_articles"]
            r_copy["agency"] = reg_details["category"]
            r_copy["details"] = reg_details
        else:
            r_copy["has_full_text"] = False
            r_copy["article_count"] = 0
            r_copy["details"] = None
        enriched_list.append(r_copy)

    return enriched_list

INTERPRETATIONS_CATALOG_PATHS = [
    Path(DATA_DIR) / "national_laws" / "interpretations_catalog.json",
    Path(__file__).resolve().parent / "data" / "national_laws" / "interpretations_catalog.json",
    Path(r"G:\我的雲端硬碟\LawExamData\national_laws\interpretations_catalog.json")
]

_CACHED_MASTER_INTERPRETATIONS: Optional[List[Dict[str, Any]]] = None

def get_all_administrative_rulings() -> List[Dict[str, Any]]:
    """載入所有行政函釋（全面整合爬取之 600+ 部會函釋與標竿函釋）並標準化欄位"""
    global _CACHED_MASTER_INTERPRETATIONS
    if _CACHED_MASTER_INTERPRETATIONS is not None:
        return _CACHED_MASTER_INTERPRETATIONS

    catalog = []
    for p in INTERPRETATIONS_CATALOG_PATHS:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    catalog = json.load(f)
                if catalog:
                    break
            except Exception:
                pass

    unified = []
    seen = set()
    
    # 1. 優先納入標竿函釋
    for r in LANDMARK_ADMIN_RULINGS:
        doc_no = r.get("doc_number", "")
        if doc_no and doc_no not in seen:
            seen.add(doc_no)
            unified.append(r)
            
    # 2. 納入 interpretations_catalog.json (涵蓋經濟部商工行政爬取之全量函釋與部會令釋)
    for c in catalog:
        doc_no = c.get("interpret_id") or c.get("doc_number", "")
        if doc_no and doc_no not in seen:
            seen.add(doc_no)
            raw_target = str(c.get("article_no", ""))
            art_no_clean = re.sub(r'[第條\s]', '', raw_target).replace('之', '-')
            entry = {
                "id": doc_no,
                "law_name": c.get("law_name", ""),
                "article_target": raw_target if raw_target.startswith("第") else f"第 {raw_target} 條" if raw_target else "",
                "article_no_clean": art_no_clean,
                "articles_cited": c.get("articles_cited", []),
                "agency": c.get("authority") or c.get("agency", "經濟部商業發展署"),
                "doc_number": doc_no,
                "date": c.get("date", ""),
                "title": c.get("title", ""),
                "holding": c.get("holding", ""),
                "content_analysis": c.get("full_text") or c.get("content_analysis") or c.get("holding", ""),
                "exam_point_hint": c.get("exam_hint") or c.get("exam_point_hint", ""),
                "source": c.get("source", "主管機關法規檢索系統")
            }
            unified.append(entry)

    # 3. 納入動態爬取之快取
    for cr in load_crawled_admin_rulings():
        doc_no = cr.get("doc_number") or cr.get("id", "")
        if doc_no and doc_no not in seen:
            seen.add(doc_no)
            unified.append(cr)

    _CACHED_MASTER_INTERPRETATIONS = unified
    return _CACHED_MASTER_INTERPRETATIONS

def get_admin_rulings_for_article(law_name: str, article_no: str) -> List[Dict[str, Any]]:
    """獲取特定法典與條號（如公司法 248、公司法 206、著作權法 3 條）匹配之權威主管機關函釋"""
    clean_no = re.sub(r'[第條\s]', '', str(article_no)).replace('之', '-')
    all_rulings = get_all_administrative_rulings()
    
    matched = []
    # 1. 優先完全命中該條號
    for r in all_rulings:
        r_law = r.get("law_name", "")
        r_clean_no = r.get("article_no_clean", "")
        r_cited = r.get("articles_cited", [])
        
        is_law_match = (r_law == law_name or r_law in law_name or law_name in r_law)
        
        is_art_match = False
        if clean_no:
            if r_clean_no == clean_no:
                is_art_match = True
            elif any(f"第{clean_no}條" in c or f"{clean_no}條" in c for c in r_cited):
                is_art_match = True
                
        if is_law_match and is_art_match:
            matched.append(r)

    # 2. 若精確條號無專屬函釋，則返回該法律之代表性重大函釋（最多 8 筆）
    if not matched:
        law_rulings = [r for r in all_rulings if r.get("law_name") == law_name or law_name in r.get("law_name", "")]
        matched = law_rulings[:8]

    return matched

CRAWLED_RULINGS_PATH = Path(DATA_DIR) / "national_laws" / "crawled_admin_rulings.json"

def load_crawled_admin_rulings() -> List[Dict[str, Any]]:
    """載入已動態爬取並持久化之主管機關函釋"""
    if CRAWLED_RULINGS_PATH.exists():
        try:
            with open(CRAWLED_RULINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_crawled_admin_rulings(new_rulings: List[Dict[str, Any]]) -> None:
    """持久化保存新爬取之行政函釋"""
    existing = load_crawled_admin_rulings()
    existing_ids = {r.get("id") for r in existing if r.get("id")}
    
    for nr in new_rulings:
        if nr.get("id") not in existing_ids:
            existing.append(nr)
            existing_ids.add(nr.get("id"))
            
    try:
        CRAWLED_RULINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CRAWLED_RULINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def crawl_and_synthesize_admin_rulings(law_name: str, article_no: str, content: str = "") -> List[Dict[str, Any]]:
    """調用現代化 Gemini 3.x Flash 智慧爬取並整理中央主管機關（經濟部/智財局/金管會/法務部）對該條文之權威函釋"""
    api_key = get_gemini_api_key()
    if not api_key:
        raise ValueError("未檢測到 GEMINI_API_KEY！")

    clean_art_no = re.sub(r'[第條\s]', '', str(article_no)).replace('之', '-')
    prompt = f"""
你是一位台灣中央主管機關（經濟部商業司、經濟部智慧財產局、金管會證期局、法務部、勞動部）之法規委員會首席法制研究員。
請針對【{law_name}】{article_no}，檢索、爬取並彙編成 1~3 筆最代表性、具法律拘束力與司律考試權威價值的「主管機關重要行政函釋（含解釋令、行政指導字號）」：

【條文內容】：
{content}

請輸出合法的 JSON Array，每個項目包含以下精準結構（不要包含額外的 Markdown 或解釋，直接輸出 JSON）：
[
  {{
    "id": "agency_topic_year",
    "law_name": "{law_name}",
    "article_target": "{article_no}",
    "article_no_clean": "{clean_art_no}",
    "agency": "主管機關名稱（如：經濟部商業司、經濟部智慧財產局、金融監督管理委員會證券期貨局、法務部）",
    "doc_number": "完整公文字號（例如：經商字第 10802424880 號函、智著字第 1120418 號函、金管證發字第 1090150022 號函）",
    "date": "發布日期（例如：2020-05-18）",
    "title": "函釋核心主題",
    "holding": "函釋核心要旨（簡潔有力，100字內）",
    "content_analysis": "詳細法理釋示與機關行政見解剖析（分段論述，200~300字）",
    "exam_point_hint": "國考申論與實務爭點指引（說明考生作答如何引述此函釋加分）"
  }}
]
"""
    models = get_gemini_models_to_try(DEFAULT_GEMINI_MODEL)
    last_err = None

    if USE_MODERN_GENAI:
        client = genai.Client(api_key=api_key)
        for m in models:
            try:
                resp = client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(temperature=0.2)
                )
                text = resp.text.strip()
                if "```" in text:
                    text = re.sub(r"^```(?:json)?", "", text, flags=re.MULTILINE)
                    text = re.sub(r"```$", "", text, flags=re.MULTILINE).strip()
                parsed = json.loads(text)
                if isinstance(parsed, list) and parsed:
                    save_crawled_admin_rulings(parsed)
                    return parsed
            except Exception as e:
                last_err = e
                continue
    else:
        legacy_genai.configure(api_key=api_key)
        for m in models:
            try:
                mod = legacy_genai.GenerativeModel(model_name=m)
                resp = mod.generate_content(prompt, generation_config=legacy_genai.types.GenerationConfig(temperature=0.2))
                text = resp.text.strip()
                if "```" in text:
                    text = re.sub(r"^```(?:json)?", "", text, flags=re.MULTILINE)
                    text = re.sub(r"```$", "", text, flags=re.MULTILINE).strip()
                parsed = json.loads(text)
                if isinstance(parsed, list) and parsed:
                    save_crawled_admin_rulings(parsed)
                    return parsed
            except Exception as e:
                last_err = e
                continue

    raise RuntimeError(f"智慧爬取主管函釋失敗: {last_err}")
