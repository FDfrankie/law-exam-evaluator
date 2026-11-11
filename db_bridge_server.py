# -*- coding: utf-8 -*-
"""
db_bridge_server.py
===================
輕量級 FastAPI 本機百萬裁判資料庫遠端橋接伺服器。
用途：
  當本機擁有完整 797 萬+ 筆 `judicial_1m_index.db` 與 `judicial_authority.db`，
  而 Streamlit Cloud（或其他裝置）需即時查詢完整大庫時，可於本機啟動本伺服器並搭配 Cloudflare Tunnel / ngrok，
  於 Streamlit Secrets 設定 `LOCAL_DB_API_URL=https://your-tunnel-url` 即可無縫穿透查詢。

啟動指令：
  uvicorn db_bridge_server:app --host 127.0.0.1 --port 8765
  或 python db_bridge_server.py
"""

from typing import Optional
from fastapi import FastAPI, Query

from build_million_judgments_db import get_million_db_engine
from judicial_appeal_chain import get_appeal_chain_engine
from authority_engine import get_engine as get_authority_engine

app = FastAPI(
    title="LawExamData Judicial DB Bridge API",
    version="1.0.0",
    description="高速唯讀穿透查詢本機 797 萬筆裁判索引與權威判例庫",
)


@app.get("/health")
def health():
    eng = get_million_db_engine()
    return {"ok": True, "mode": eng.db_mode, "available": eng.is_available()}


@app.get("/stats")
def stats():
    eng = get_million_db_engine()
    info = eng.get_db_info()
    try:
        auth_stats = get_authority_engine().get_authority_stats()
    except Exception:
        auth_stats = {}
    return {**info, "authority": auth_stats}


@app.get("/search")
def search(
    query: str = "",
    jud_year: str = "",
    jud_word: str = "",
    jud_no: str = "",
    case_cause: str = "",
    main_holding: str = "",
    argument_issue: str = "",
    cited_laws: str = "",
    case_type: str = "全部",
    court_system: str = "全部法院 (全體司法體系)",
    filter_no_legal_issue: bool = True,
    top_k: int = Query(default=20, ge=1, le=100),
):
    eng = get_million_db_engine()
    return eng.search_fts_and_meta(
        query=query,
        jud_year=jud_year,
        jud_word=jud_word,
        jud_no=jud_no,
        case_cause=case_cause,
        main_holding=main_holding,
        argument_issue=argument_issue,
        cited_laws=cited_laws,
        case_type=case_type,
        court_system=court_system,
        filter_no_legal_issue=filter_no_legal_issue,
        top_k=top_k,
    )


@app.get("/lookup")
def lookup(citation: str):
    eng = get_million_db_engine()
    res = eng.find_by_citation(citation)
    return res if res else {"found": False, "citation": citation}


@app.get("/redirect")
def redirect_target(case_id: str):
    eng = get_million_db_engine()
    res = eng.get_redirect_target(case_id)
    return res if res else {"is_redirect": False, "case_id": case_id}


@app.get("/appeal_chain")
def appeal_chain(
    case_id: str = "",
    court: str = "",
    year: str = "",
    word: str = "",
    no: str = "",
):
    return get_appeal_chain_engine().get_appeal_chain(
        case_id=case_id, court=court, year=year, word=word, no=no
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)
