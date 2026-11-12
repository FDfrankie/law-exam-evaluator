"""Reusable client-side study/exam timers and wrong-MCQ review notebook components."""

import json
import html as _html
from typing import Any, Callable, Dict, List, Optional
import streamlit as st
import streamlit.components.v1 as components

from ui.navigation import navigate_to


def render_study_timer_widget(
    default_exam_date: str = "2026-08-01",
    height: int = 168,
) -> None:
    """Render a zero-rerun client-side exam countdown + 25/5 Pomodoro timer in HTML/JS."""
    safe_date = _html.escape(default_exam_date, quote=True)
    widget_html = f"""
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8" />
<style>
  * {{ box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans TC", sans-serif; }}
  body {{ margin: 0; padding: 0; background: transparent; color: #0f172a; }}
  .card {{
    background: linear-gradient(135deg, #f8fafc 0%, #eff6ff 100%);
    border: 1px solid #bfdbfe;
    border-radius: 10px;
    padding: 9px 10px;
  }}
  .row {{ display: flex; align-items: center; justify-content: space-between; gap: 6px; }}
  .title {{ font-size: 11.5px; font-weight: 700; color: #1e3a8a; }}
  .days-pill {{
    background: #1d4ed8; color: #fff; font-size: 11.5px; font-weight: 700;
    padding: 2px 8px; border-radius: 999px; white-space: nowrap;
  }}
  .date-row {{ margin-top: 5px; display: flex; align-items: center; justify-content: space-between; gap: 6px; }}
  .date-row label {{ font-size: 11px; color: #475569; }}
  input[type="date"] {{
    font-size: 11px; padding: 2px 5px; border: 1px solid #cbd5e1;
    border-radius: 6px; background: #fff; color: #1e293b;
  }}
  .divider {{ height: 1px; background: #dbeafe; margin: 7px 0; }}
  .pomo-display {{
    font-size: 20px; font-weight: 800; color: #0f172a; letter-spacing: 0.5px;
    font-variant-numeric: tabular-nums;
  }}
  .phase {{ font-size: 11px; font-weight: 600; color: #2563eb; }}
  .btn-group {{ display: flex; gap: 4px; margin-top: 6px; }}
  button {{
    flex: 1; font-size: 11px; font-weight: 600; padding: 4px 5px; border-radius: 6px;
    border: 1px solid #cbd5e1; background: #fff; color: #1e293b; cursor: pointer;
  }}
  button:hover {{ background: #f1f5f9; }}
  button.primary {{ background: #2563eb; color: #fff; border-color: #1d4ed8; }}
  button.primary:hover {{ background: #1d4ed8; }}
</style>
</head>
<body>
<div class="card">
  <div class="row">
    <span class="title">📅 司律備考倒數</span>
    <span id="daysBadge" class="days-pill">計算中...</span>
  </div>
  <div class="date-row">
    <label for="examDateInput">目標考期：</label>
    <input id="examDateInput" type="date" value="{safe_date}" />
  </div>
  <div class="divider"></div>
  <div class="row">
    <div>
      <div id="pomoPhase" class="phase">🍅 專注衝刺 (25分)</div>
    </div>
    <div id="pomoClock" class="pomo-display">25:00</div>
  </div>
  <div class="btn-group">
    <button id="btnToggle" class="primary" type="button">開始</button>
    <button id="btnMode" type="button">切換休息</button>
    <button id="btnReset" type="button">重設</button>
  </div>
</div>
<script>
(function() {{
  var STORAGE_DATE_KEY = "lawexam_target_exam_date";
  var dateInput = document.getElementById("examDateInput");
  var daysBadge = document.getElementById("daysBadge");
  var pomoClock = document.getElementById("pomoClock");
  var pomoPhase = document.getElementById("pomoPhase");
  var btnToggle = document.getElementById("btnToggle");
  var btnMode = document.getElementById("btnMode");
  var btnReset = document.getElementById("btnReset");

  try {{
    var saved = localStorage.getItem(STORAGE_DATE_KEY);
    if (saved) dateInput.value = saved;
  }} catch (e) {{}}

  function updateCountdown() {{
    var v = dateInput.value || "{safe_date}";
    try {{ localStorage.setItem(STORAGE_DATE_KEY, v); }} catch (e) {{}}
    var now = new Date();
    var todayMid = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var parts = v.split("-");
    if (parts.length !== 3) return;
    var target = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
    var diffDays = Math.ceil((target.getTime() - todayMid.getTime()) / 86400000);
    if (diffDays > 0) {{
      daysBadge.textContent = "倒數 " + diffDays + " 天";
    }} else if (diffDays === 0) {{
      daysBadge.textContent = "今日應考！";
    }} else {{
      daysBadge.textContent = "已過 " + Math.abs(diffDays) + " 天";
    }}
  }}
  dateInput.addEventListener("change", updateCountdown);
  updateCountdown();

  var isFocus = true;
  var remaining = 25 * 60;
  var timerId = null;

  function renderClock() {{
    var mins = Math.floor(remaining / 60);
    var secs = remaining % 60;
    pomoClock.textContent = (mins < 10 ? "0" : "") + mins + ":" + (secs < 10 ? "0" : "") + secs;
    pomoPhase.textContent = isFocus ? "🍅 專注衝刺 (25分)" : "☕ 護眼休息 (05分)";
    btnMode.textContent = isFocus ? "切換休息" : "切換專注";
  }}

  function stopTimer() {{
    if (timerId !== null) {{
      clearInterval(timerId);
      timerId = null;
    }}
    btnToggle.textContent = "開始";
  }}

  btnToggle.addEventListener("click", function() {{
    if (timerId !== null) {{
      stopTimer();
      return;
    }}
    btnToggle.textContent = "暫停";
    timerId = setInterval(function() {{
      if (remaining > 0) {{
        remaining -= 1;
        renderClock();
      }} else {{
        stopTimer();
        isFocus = !isFocus;
        remaining = (isFocus ? 25 : 5) * 60;
        renderClock();
      }}
    }}, 1000);
  }});

  btnMode.addEventListener("click", function() {{
    stopTimer();
    isFocus = !isFocus;
    remaining = (isFocus ? 25 : 5) * 60;
    renderClock();
  }});

  btnReset.addEventListener("click", function() {{
    stopTimer();
    remaining = (isFocus ? 25 : 5) * 60;
    renderClock();
  }});

  renderClock();
}})();
</script>
</body>
</html>
"""
    components.html(widget_html, height=height)


def render_exam_pacing_timer(
    total_questions: int,
    minutes_per_q: float = 1.2,
    height: int = 86,
) -> None:
    """Render a zero-rerun client-side mock-exam pacing stopwatch/countdown bar."""
    q_count = max(1, int(total_questions or 1))
    total_seconds = max(60, int(round(q_count * minutes_per_q * 60)))
    total_minutes_disp = round(total_seconds / 60, 1)
    pace_html = f"""
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8" />
<style>
  * {{ box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans TC", sans-serif; }}
  body {{ margin: 0; padding: 0; background: transparent; }}
  .bar {{
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 10px;
    padding: 8px 12px;
  }}
  .meta {{ font-size: 12px; color: #334155; }}
  .meta strong {{ color: #1e3a8a; }}
  .clock {{ font-size: 20px; font-weight: 800; color: #0f172a; font-variant-numeric: tabular-nums; }}
  .clock.warn {{ color: #dc2626; }}
  .btns {{ display: flex; gap: 6px; }}
  button {{
    font-size: 12px; font-weight: 600; padding: 5px 10px; border-radius: 6px;
    border: 1px solid #cbd5e1; background: #fff; color: #1e293b; cursor: pointer;
  }}
  button.primary {{ background: #1d4ed8; color: #fff; border-color: #1e40af; }}
</style>
</head>
<body>
<div class="bar">
  <div class="meta">
    ⏱️ <strong>全真限時配速器</strong><br />
    共 {q_count} 題 ｜ 建議時限 {total_minutes_disp} 分鐘 (約 {minutes_per_q:.1f} 分/題)
  </div>
  <div id="examClock" class="clock">--:--</div>
  <div class="btns">
    <button id="btnStartPause" class="primary" type="button">開始計時</button>
    <button id="btnExamReset" type="button">重設</button>
  </div>
</div>
<script>
(function() {{
  var total = {total_seconds};
  var left = total;
  var handle = null;
  var clockEl = document.getElementById("examClock");
  var toggleEl = document.getElementById("btnStartPause");
  var resetEl = document.getElementById("btnExamReset");

  function fmt(sec) {{
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    var mm = (m < 10 ? "0" : "") + m;
    var ss = (s < 10 ? "0" : "") + s;
    return h > 0 ? (h + ":" + mm + ":" + ss) : (mm + ":" + ss);
  }}

  function draw() {{
    clockEl.textContent = fmt(left);
    if (left <= 60) {{
      clockEl.classList.add("warn");
    }} else {{
      clockEl.classList.remove("warn");
    }}
  }}

  function stop() {{
    if (handle !== null) {{
      clearInterval(handle);
      handle = null;
    }}
    toggleEl.textContent = "開始計時";
  }}

  toggleEl.addEventListener("click", function() {{
    if (handle !== null) {{
      stop();
      return;
    }}
    toggleEl.textContent = "暫停";
    handle = setInterval(function() {{
      if (left > 0) {{
        left -= 1;
        draw();
      }} else {{
        stop();
        clockEl.textContent = "時間到 00:00";
      }}
    }}, 1000);
  }});

  resetEl.addEventListener("click", function() {{
    stop();
    left = total;
    draw();
  }});

  draw();
}})();
</script>
</body>
</html>
"""
    components.html(pace_html, height=height)


def build_wrong_mcq_retry_exam(
    wrong_items: List[Dict[str, Any]],
    subject_label: str = "錯題複習特訓",
) -> Dict[str, Any]:
    """Convert stored wrong-MCQ rows into a playable stage1_exam_data payload."""
    questions: List[Dict[str, Any]] = []
    answer_key: Dict[str, str] = {}

    for idx, item in enumerate(wrong_items, 1):
        q_data = item.get("question_data")
        if not isinstance(q_data, dict):
            try:
                q_data = json.loads(item.get("question_json") or "{}")
            except Exception:
                q_data = {}
        opts = q_data.get("options") or item.get("options") or {}
        if isinstance(opts, list):
            opts = {chr(ord("A") + i): str(v) for i, v in enumerate(opts)}
        c_ans = str(
            item.get("correct_answer")
            or q_data.get("answer")
            or q_data.get("correct_answer")
            or "A"
        ).strip().upper()
        q_entry = {
            "question_no": idx,
            "category": item.get("subject") or q_data.get("category") or "錯題特訓",
            "case_facts": q_data.get("case_facts", ""),
            "question": item.get("question") or q_data.get("question") or q_data.get("stem") or "",
            "options": opts,
            "answer": c_ans,
            "explanation": item.get("explanation") or q_data.get("explanation") or "",
            "core_issue": q_data.get("core_issue", ""),
            "legal_references": item.get("law_cited") or q_data.get("legal_references") or "",
            "question_hash": item.get("question_hash", ""),
        }
        questions.append(q_entry)
        answer_key[str(idx)] = c_ans

    return {
        "subject": subject_label,
        "topic": f"{subject_label} ({len(questions)} 題重練)",
        "questions": questions,
        "answer_key": answer_key,
    }


def _load_wrong_mcq_fns():
    from question_bank_engine import (
        get_subject_accuracy_stats,
        get_wrong_mcqs,
        mark_wrong_mcq_mastered,
        export_wrong_mcqs_csv,
    )
    return (
        get_subject_accuracy_stats,
        get_wrong_mcqs,
        mark_wrong_mcq_mastered,
        export_wrong_mcqs_csv,
    )


def render_wrong_mcq_notebook_panel(
    *,
    mode_gen_name: str,
    key_prefix: str = "wnb",
    get_stats_fn: Optional[Callable[[], Dict[str, Any]]] = None,
    get_wrongs_fn: Optional[Callable[..., List[Dict[str, Any]]]] = None,
    mark_mastered_fn: Optional[Callable[[str, bool], bool]] = None,
    export_csv_fn: Optional[Callable[..., str]] = None,
) -> None:
    """Render per-subject wrong-MCQ weakness analytics, Anki CSV export, and instant retry."""
    st.markdown("### 📌 錯題複習特訓 & 考科弱點分析")
    st.caption("司律一試練習與線上批改中答錯的選擇題會自動累進追蹤於此；支援依考科過濾、標記精熟、匯出 Anki CSV 記憶卡及一鍵錯題重練！")

    if not all([get_stats_fn, get_wrongs_fn, mark_mastered_fn, export_csv_fn]):
        default_stats, default_wrongs, default_mark, default_csv = _load_wrong_mcq_fns()
        get_stats_fn = get_stats_fn or default_stats
        get_wrongs_fn = get_wrongs_fn or default_wrongs
        mark_mastered_fn = mark_mastered_fn or default_mark
        export_csv_fn = export_csv_fn or default_csv

    stats = get_stats_fn() or {}
    total_rec = int(stats.get("total", 0))
    total_unmastered = int(stats.get("total_unmastered", 0))
    total_mastered = int(stats.get("total_mastered", 0))
    total_attempts = int(stats.get("total_wrong_attempts", 0))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("累計收錄錯題", f"{total_rec} 題")
    m2.metric("待複習未精熟", f"{total_unmastered} 題")
    m3.metric("已標記精熟", f"{total_mastered} 題")
    m4.metric("累計答錯次數", f"{total_attempts} 次")

    subjects_map: Dict[str, Dict[str, Any]] = stats.get("subjects", {}) or {}
    if subjects_map:
        with st.expander("📊 各考科弱點分布統計", expanded=True):
            subj_items = list(subjects_map.items())
            cols = st.columns(min(4, max(1, len(subj_items))))
            for idx, (s_name, s_info) in enumerate(subj_items):
                with cols[idx % len(cols)]:
                    st.metric(
                        label=s_name,
                        value=f"待補 {s_info.get('unmastered', 0)} 題",
                        delta=f"精熟率 {s_info.get('mastery_rate', 0.0)}% (累錯 {s_info.get('wrong_count_sum', 0)} 次)",
                    )

    f1, f2 = st.columns([2, 1])
    with f1:
        subj_opts = ["全部科目"] + sorted(list(subjects_map.keys()))
        sel_subj = st.selectbox("依考科篩選錯題：", subj_opts, key=f"{key_prefix}_subj_filter")
    with f2:
        st.write("")
        include_mastered = st.checkbox("顯示已精熟錯題", value=False, key=f"{key_prefix}_inc_mastered")

    wrong_items = get_wrongs_fn(subject=sel_subj, include_mastered=include_mastered, limit=100) or []

    if not wrong_items:
        st.info("🎉 目前沒有符合篩選條件的待複習錯題！前往【AI 智慧命題】完成測驗並交卷批改，錯題將自動紀錄於此。")
        return

    a1, a2 = st.columns([1.4, 1.4])
    with a1:
        if st.button("🎯 錯題重練（開啟本清單實戰測驗）", type="primary", use_container_width=True, key=f"{key_prefix}_retry_btn"):
            retry_pool = [w for w in wrong_items if not w.get("mastered")][:20] or wrong_items[:20]
            subj_title = sel_subj if sel_subj != "全部科目" else "全科錯題特訓"
            retry_exam = build_wrong_mcq_retry_exam(retry_pool, subject_label=subj_title)
            for k in list(st.session_state.keys()):
                if k.startswith("user_choice_") or k.startswith("rep_res_") or k.startswith("rep_input_"):
                    del st.session_state[k]
            st.session_state.pop("stage1_graded", None)
            st.session_state.pop("stage1_user_answers", None)
            st.session_state.pop("stage1_wrong_recorded_sig", None)
            st.session_state["stage1_exam_data"] = retry_exam
            navigate_to(mode_gen_name, rerun=True)

    with a2:
        try:
            csv_data = export_csv_fn(include_mastered=True)
            st.download_button(
                label="📥 匯出 Anki CSV 錯題卡",
                data=csv_data.encode("utf-8"),
                file_name="司律一試錯題本_Anki.csv",
                mime="text/csv",
                use_container_width=True,
                key=f"{key_prefix}_export_anki_csv",
            )
        except Exception as e_csv:
            st.caption(f"CSV 匯出待命：{e_csv}")

    st.divider()
    for idx, item in enumerate(wrong_items, 1):
        q_hash = item.get("question_hash", f"row_{idx}")
        subj = item.get("subject", "法學綜合")
        is_m = bool(item.get("mastered"))
        w_cnt = int(item.get("wrong_count", 1))
        status_tag = "✅ 已精熟" if is_m else f"🔥 累錯 {w_cnt} 次"
        q_text = str(item.get("question", "")).strip()
        preview = (q_text[:34] + "...") if len(q_text) > 34 else q_text

        with st.expander(f"{idx}. 【{subj}】{status_tag} ｜ {preview}", expanded=(idx <= 2 and not is_m)):
            st.write(q_text)
            opts = item.get("options") or {}
            if isinstance(opts, dict) and opts:
                for opt_k in ["A", "B", "C", "D"]:
                    if opt_k in opts:
                        st.markdown(f"- **({opt_k})** {opts[opt_k]}")
            u_ch = item.get("user_choice") or "未作答"
            c_ch = item.get("correct_answer") or ""
            st.markdown(f"上次選答：**({u_ch})** ｜ 正確答案：**({c_ch})** ｜ 關聯法條：`{item.get('law_cited') or '無標註'}`")
            if item.get("explanation"):
                st.info(f"**詳細解析：**\n{item['explanation']}")

            btn_lbl = "🔁 取消精熟（重新納入複習）" if is_m else "✅ 標記已精熟"
            if st.button(btn_lbl, key=f"{key_prefix}_toggle_m_{q_hash}_{idx}"):
                mark_mastered_fn(q_hash, not is_m)
                st.rerun()
