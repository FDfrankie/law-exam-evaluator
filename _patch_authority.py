target_path = r"G:\我的雲端硬碟\LawExamData\code\authority_engine.py"
with open(target_path, "r", encoding="utf-8") as f:
    content = f.read()

target = """            conn.execute("CREATE INDEX IF NOT EXISTS idx_prec_sys ON precedents(sys_type);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prec_caseno ON precedents(case_no);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prec_status ON precedents(status);")"""

replacement = """            # 動態補齊可能缺失之欄位 (兼容 crawl_all_precedents.py 與權威引擎架構)
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(precedents);")
            existing_cols = {row[1] for row in cur.fetchall()}
            for col_name in ["id", "precedent_id", "case_no", "year", "court", "title", "reasoning", "full_text", "subject", "sub_category", "extra_meta", "abolition_note", "source_url"]:
                if col_name not in existing_cols:
                    try:
                        conn.execute(f"ALTER TABLE precedents ADD COLUMN {col_name} TEXT;")
                        existing_cols.add(col_name)
                    except Exception:
                        pass

            try:
                conn.execute("UPDATE precedents SET case_no = precedent_id WHERE (case_no IS NULL OR case_no = '') AND precedent_id IS NOT NULL;")
                conn.execute("UPDATE precedents SET id = precedent_id WHERE (id IS NULL OR id = '') AND precedent_id IS NOT NULL;")
                conn.execute("UPDATE precedents SET reasoning = full_text WHERE (reasoning IS NULL OR reasoning = '') AND full_text IS NOT NULL;")
            except Exception:
                pass

            conn.execute("CREATE INDEX IF NOT EXISTS idx_prec_sys ON precedents(sys_type);")
            if "case_no" in existing_cols:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_prec_caseno ON precedents(case_no);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prec_status ON precedents(status);")"""

if target in content:
    content = content.replace(target, replacement, 1)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Successfully patched authority_engine.py")
else:
    # Try normalized newlines
    normalized_c = content.replace("\r\n", "\n")
    if target in normalized_c:
        normalized_c = normalized_c.replace(target, replacement, 1)
        with open(target_path, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(normalized_c)
        print("Successfully patched authority_engine.py with newline normalization")
    else:
        print("Target not found!")
