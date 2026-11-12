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

from typing import Any, Dict, Optional
import hmac
import logging
import os
import re

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from build_million_judgments_db import get_million_db_engine
from judicial_appeal_chain import get_appeal_chain_engine
from authority_engine import get_engine as get_authority_engine

logger = logging.getLogger(__name__)

_PATH_KEYS_TO_REDACT = frozenset({
    "path",
    "index_db_path",
    "db_path",
    "shards_dir",
    "base_dir",
    "inbox_dir",
})
_LOCAL_PATH_RE = re.compile(r"^(?:[A-Za-z]:[/\\]|\\\\|/)")

app = FastAPI(
    title="LawExamData Judicial DB Bridge API",
    version="1.0.0",
    description="高速唯讀穿透查詢本機 797 萬筆裁判索引與權威判例庫",
)

_cors_origins_raw = os.getenv("DB_BRIDGE_CORS_ORIGINS", "*").strip()
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def _get_bridge_token() -> str:
    return os.getenv("DB_BRIDGE_TOKEN", "").strip()


def verify_bearer_token(authorization: Optional[str] = Header(default=None)) -> None:
    """Validate optional Bearer token configured via DB_BRIDGE_TOKEN."""
    expected = _get_bridge_token()
    if not expected:
        return
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization scheme; expected Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    provided = parts[1].strip()
    if not provided or not hmac.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _redact_local_paths(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Remove local filesystem path fields and path-like string values."""
    cleaned: Dict[str, Any] = {}
    for key, val in payload.items():
        if key in _PATH_KEYS_TO_REDACT:
            continue
        if isinstance(val, str) and _LOCAL_PATH_RE.match(val.strip()):
            continue
        if isinstance(val, dict):
            cleaned[key] = _redact_local_paths(val)
        else:
            cleaned[key] = val
    return cleaned


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return clean JSON error without leaking raw tracebacks or local paths."""
    logger.exception("Unhandled error in db_bridge_server on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": "Internal server error"},
    )


@app.get("/health")
def health():
    eng = get_million_db_engine()
    return {
        "ok": True,
        "mode": getattr(eng, "db_mode", "unknown"),
        "available": bool(eng.is_available()),
    }


@app.get("/stats", dependencies=[Depends(verify_bearer_token)])
def stats():
    eng = get_million_db_engine()
    raw_info = eng.get_db_info()
    info = _redact_local_paths(raw_info) if isinstance(raw_info, dict) else {}
    try:
        auth_eng = get_authority_engine()
        try:
            raw_auth = auth_eng.get_authority_stats(read_only=True)
        except TypeError:
            raw_auth = auth_eng.get_authority_stats()
        auth_stats = _redact_local_paths(raw_auth) if isinstance(raw_auth, dict) else {}
    except Exception:
        auth_stats = {}
    return {**info, "authority": auth_stats}


@app.get("/search", dependencies=[Depends(verify_bearer_token)])
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


@app.get("/lookup", dependencies=[Depends(verify_bearer_token)])
def lookup(citation: str):
    eng = get_million_db_engine()
    res = eng.find_by_citation(citation)
    return res if res else {"found": False, "citation": citation}


@app.get("/redirect", dependencies=[Depends(verify_bearer_token)])
def redirect_target(case_id: str):
    eng = get_million_db_engine()
    res = eng.get_redirect_target(case_id)
    return res if res else {"is_redirect": False, "case_id": case_id}


@app.get("/appeal_chain", dependencies=[Depends(verify_bearer_token)])
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
