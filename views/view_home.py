import streamlit as st
from views.constants import (
    MODE_HOME, MODE_EVAL, MODE_GEN, MODE_BANK, MODE_ANS,
    MODE_SEARCH, MODE_QA, MODE_SUMMARIZER, MODE_SIX_CODES, MODE_SFT
)
from views.common import load_all_existing_stage1_mcqs
try:
    from legal_query_engine import get_precedents_catalog
except Exception:
    get_precedents_catalog = lambda: []
try:
    from admin_rulings_engine import get_all_administrative_rulings
except Exception:
    get_all_administrative_rulings = lambda: []

def render_mode_home():
    st.title("🏛️ 司律考試 AI 評分、智慧命題與法學裁判樞紐")
    st.markdown("##### 專為中華民國司法官、律師高考、法研所與轉學考打造之全方位法學研習智能平台")
    st.caption("結合最新 Gemini 多模態神經網路、全國 5.2 萬條法規、2,100+ 權威裁判判例決議、628+ 中央部會函釋與一試跨科全真題庫。")
    st.write("")

    # 四大資料庫即時統計指標
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    with m_col1:
        st.metric(
            label="📜 全國法規條文庫",
            value="52,000+ 條",
            delta="六法全書與立法沿革"
        )
    with m_col2:
        try:
            total_precedents_count = len(get_precedents_catalog() or [])
        except Exception:
            total_precedents_count = 2104
        st.metric(
            label="⚖️ 權威裁判・判例・座談會",
            value=f"{total_precedents_count:,} 筆",
            delta="大法庭/原判例/決議/座談會"
        )
    with m_col3:
        try:
            from admin_rulings_engine import get_all_administrative_rulings
            total_rulings_count = len(get_all_administrative_rulings() or [])
        except Exception:
            total_rulings_count = 628
        st.metric(
            label="🏛️ 中央部會權威函釋",
            value=f"{total_rulings_count:,} 則",
            delta="經商/金管/勞動/智財/法務"
        )
    with m_col4:
        try:
            all_stage1_qs = load_all_existing_stage1_mcqs()
            total_mcqs_count = len(all_stage1_qs)
        except Exception:
            total_mcqs_count = 380
        st.metric(
            label="🎯 一試跨科實戰題庫",
            value=f"{total_mcqs_count:,} 題",
            delta="跨科全真模考與詳解"
        )

    st.divider()

    # 九大核心模組導覽卡片
    st.subheader("🧭 九大核心功能模組導覽與快速進入")
    st.caption("點擊下方對應模組之「🚀 立即前往」按鈕，即可快速跳轉至該功能進行演練與查詢。")

    card_rows = [
        [
            ("📝 試卷評分與手寫辨識", "支援拍照、手寫掃描 PDF、Word 電子稿等多模態視覺辨識，依考選部四大評分指標進行榜首級 IRAC 評閱診斷。", MODE_EVAL),
            ("🎯 司律模擬出題", "支援自選題數一試選擇題（含盲測盲題、答案速查表與考點診斷）及二試申論實例題，搭載垂直爭點累加清單。", MODE_GEN),
            ("📚 歷年真題庫檢索與模擬演練", "涵蓋臺大法研所、臺大轉學考、考選部司法官律師、司法特考歷年真題，支援在線實戰作答與自動批改。", MODE_BANK)
        ],
        [
            ("📖 高分權威擬答生成", "以榜首級 IRAC 三段論法架構，融入最新大法庭裁定、指標判例與權威學者獨門暗器見解，快速產出二試頂級擬答。", MODE_ANS),
            ("🔍 統一法學檢索樞紐與判決研析", "整合布林檢索、法院體系字號精準查詢、爭點大典、案例橫向比對（相同見解 vs 相反見解）與審級脈絡更迭鏈。", MODE_SEARCH),
            ("💬 專屬法學全能問答樞紐", "支援日常法律諮詢、國考爭點論辯、法條精準定位、專業書狀草擬及車禍折舊、資遣費、剩餘財產金額精算工具。", MODE_QA)
        ],
        [
            ("📑 一鍵 AI 判解與長篇函釋精鍊", "深度消化數萬字冗長判決書或部會函釋，一鍵提煉「主文、核心爭點、實務見解、學說評釋與國考作答破題金句」。", MODE_SUMMARIZER),
            ("⚖️ 智慧六法與條文判解標註", "全方位整合全國法規條文、立法院三讀立法理由、沿革修正對照、關聯實務字號、重要行政函釋與筆記關聯。", MODE_SIX_CODES),
            ("📥 手寫筆記蒸餾與大庫管理", "支援多引擎解壓司法院 Open Data RAR/ZIP 打包檔，並將筆記與考卷一鍵蒸餾轉化為百萬筆 SFT 法律微調大庫。", MODE_SFT)
        ]
    ]

    for r_idx, row in enumerate(card_rows):
        cols = st.columns(3)
        for c_idx, (c_title, c_desc, c_mode) in enumerate(row):
            with cols[c_idx]:
                with st.container(border=True):
                    st.markdown(f"##### {c_title}")
                    st.write(c_desc)
                    if st.button("🚀 立即前往", key=f"btn_jump_mode_{r_idx}_{c_idx}", use_container_width=True):
                        st.session_state["app_mode"] = c_mode
                        st.rerun()

    st.divider()

    # 隱私權政策、著作權政策與法律免責聲明
    pol_c1, pol_c2, pol_c3 = st.columns(3)
    with pol_c1:
        with st.container(border=True):
            st.markdown("#### 🔒 隱私權保護政策")
            st.caption("依中華民國《個人資料保護法》及相關法規辦理")
            st.markdown(
                """
1. **資料蒐集與用途**：本平臺使用者所上傳之手寫試卷、自訂筆記、作答紀錄與各類文件，僅限於當次瀏覽器工作階段中進行 AI 辨識、爭點解析、出題與評閱，絕不用於未授權之第三方商業散布。
2. **金鑰與憑證安全**：使用者於本系統設定之 `GEMINI_API_KEY` 及司法院開放平臺帳號密碼，均僅保存在當前瀏覽器 `st.session_state` 暫存記憶體中，絕不寫入公開原始碼、日誌或持久端伺服器資料庫。
3. **資料控制權**：使用者得隨時於側邊欄點擊「清除 Token」或重整瀏覽器以完全銷毀工作階段記憶體中的敏感資訊。
                """
            )
    with pol_c2:
        with st.container(border=True):
            st.markdown("#### 📜 著作權與合理使用政策")
            st.caption("依中華民國《著作權法》第 9 條、第 52 條與第 65 條規範")
            st.markdown(
                """
1. **公務著作公共領域**：本平臺收錄之中華民國憲法、法律、命令、司法院裁判書全文、最高法院裁判、最高行政法院裁判、原判例、庭長法官聯席會議決議、法律座談會研討結論、中央部會行政函釋及考選部歷年公務人員高考與專技國考試題，依《著作權法》第 9 條第 1 項規定，**不得為著作權之標的**，屬全體國民共享之公共領域公有財產。
2. **學說與筆記合理使用**：系統中所引用之學者學說爭點、教科書要旨與個人筆記重點，係為法學學術研析、國考教學與個人學習之必要正當目的，符合《著作權法》第 52 條及第 65 條第 2 項之合理使用範圍。
                """
            )
    with pol_c3:
        with st.container(border=True):
            st.markdown("#### ⚖️ 法律免責聲明")
            st.caption("依中華民國《法院組織法》及法學研習專業指引聲明")
            st.markdown(
                """
1. **非正式法律意見**：本系統所生成之試卷批改、考點建議、IRAC 高分擬答、案例橫向比對分析及金額試算結果，均由大型語言模型及演算法自動生成，僅供法律學術研習、司法官律師高考準備及司法特考演練參考，**不構成任何形式之正式法律意見、訴訟諮詢或委任要約**。
2. **原判例效力說明**：依《法院組織法》第 57 條之 1 規定，最高法院於中華民國 108 年 7 月 4 日前依法選編之判例，若無裁判全文者停止適用；其有裁判全文者，其效力與未經選編為判例之最高法院裁判相同。本平臺收錄之「原判例」均已依法註明裁判全文字號，供考生對照歷史法理脈絡。
3. **個案具體適用**：具體訴訟爭議請洽詢中華民國合格執業律師或尋求法律扶助基金會專業協助。
                """
            )


