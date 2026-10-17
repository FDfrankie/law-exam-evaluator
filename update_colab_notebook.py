import os
import sys
import json
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

nb_path = Path("G:/我的雲端硬碟/LawExamData/code/train_colab.ipynb")
with open(nb_path, "r", encoding="utf-8") as f:
    nb = json.load(f)

# 1. Update Cell 1
for cell in nb.get("cells", []):
    src = cell.get("source", [])
    src_text = "".join(src)
    if "DATASET_MODE" in src_text:
        cell["source"] = [
            "# 1. 掛載 Google 雲端硬碟 (直接讀取既有數據，無需重複上傳)\n",
            "import os\n",
            "from google.colab import drive\n",
            "drive.mount('/content/drive')\n",
            "\n",
            "#@title 選擇微調資料集規模 (Dataset Selection)\n",
            "#@markdown 支援「10萬筆黃金加權平衡庫 (手寫筆記+真題重點加權，強烈推薦)」、「100萬筆全真統一大庫」或「5,082筆純核實核心庫」：\n",
            "DATASET_MODE = \"10萬筆黃金加權平衡庫 (Balanced SFT - 推薦)\" #@param [\"10萬筆黃金加權平衡庫 (Balanced SFT - 推薦)\", \"100萬筆全真統一大庫 (1M+ Unified SFT)\", \"5,082筆純核實核心庫 (Verified SFT)\"]\n",
            "\n",
            "if \"加權\" in DATASET_MODE or \"Balanced\" in DATASET_MODE:\n",
            "    file_name = \"law_exam_balanced_weighted_sft.jsonl\"\n",
            "elif \"100萬\" in DATASET_MODE:\n",
            "    file_name = \"law_exam_master_sft_unified.jsonl\"\n",
            "else:\n",
            "    file_name = \"law_exam_verified_sft.jsonl\"\n",
            "\n",
            "possible_paths = [\n",
            "    f'/content/drive/MyDrive/LawExamData/training_data/{file_name}',\n",
            "    f'/content/drive/我的雲端硬碟/LawExamData/training_data/{file_name}',\n",
            "    f'/content/drive/MyDrive/LawExamData/training_data/law_exam_balanced_weighted_sft.jsonl',\n",
            "    f'/content/drive/我的雲端硬碟/LawExamData/training_data/law_exam_balanced_weighted_sft.jsonl',\n",
            "    f'/content/drive/MyDrive/LawExamData/training_data/law_exam_master_sft_unified.jsonl',\n",
            "    f'/content/drive/我的雲端硬碟/LawExamData/training_data/law_exam_master_sft_unified.jsonl',\n",
            "    f'/content/drive/MyDrive/LawExamData/training_data/law_exam_verified_sft.jsonl'\n",
            "]\n",
            "DATA_PATH = None\n",
            "for p in possible_paths:\n",
            "    if os.path.exists(p):\n",
            "        DATA_PATH = p\n",
            "        break\n",
            "if not DATA_PATH:\n",
            "    DATA_PATH = possible_paths[0]\n",
            "\n",
            "print('✅ 訓練資料集已就緒：', DATA_PATH)\n"
        ]
        break

# 2. Update Cell 4
for cell in nb.get("cells", []):
    src = cell.get("source", [])
    src_text = "".join(src)
    if "formatting_prompts_func" in src_text:
        cell["source"] = [
            "# 4. 載入資料並格式化為 ChatML 指令提示詞\n",
            "from datasets import load_dataset, Features, Value\n",
            "from trl import SFTTrainer\n",
            "from transformers import TrainingArguments\n",
            "import random\n",
            "\n",
            "# 明確定義 SFT 特徵綱要，確保任何來源之 JSONL 均能無縫載入並徹底避免 CastError\n",
            "sft_features = Features({\n",
            "    \"id\": Value(\"string\"),\n",
            "    \"source_type\": Value(\"string\"),\n",
            "    \"instruction\": Value(\"string\"),\n",
            "    \"input\": Value(\"string\"),\n",
            "    \"output\": Value(\"string\"),\n",
            "})\n",
            "\n",
            "try:\n",
            "    dataset = load_dataset('json', data_files=DATA_PATH, split='train', features=sft_features)\n",
            "except Exception as e:\n",
            "    print('Features load failed, falling back to standard json loader:', e)\n",
            "    dataset = load_dataset('json', data_files=DATA_PATH, split='train')\n",
            "\n",
            "#@title 來源權重動態平衡 (Data Mixture Weighting)\n",
            "#@markdown 是否啟用來源動態加權 (推薦啟用，避免手寫筆記與真題被百萬模板稀釋)：\n",
            "ENABLE_DYNAMIC_WEIGHTING = True #@param {type:\"boolean\"}\n",
            "NOTE_WEIGHT = 500 #@param {type:\"integer\"} 手寫筆記放大倍率\n",
            "EXAM_WEIGHT = 50  #@param {type:\"integer\"} 司律真題放大倍率\n",
            "COURT_WEIGHT = 15 #@param {type:\"integer\"} 憲法與裁判放大倍率\n",
            "\n",
            "if ENABLE_DYNAMIC_WEIGHTING and \"source_type\" in dataset.column_names:\n",
            "    print('⚖️ 正在套用來源權重過採樣 (Weighted Oversampling)...')\n",
            "    sts = dataset[\"source_type\"]\n",
            "    idx_pool = []\n",
            "    n_cnt, e_cnt, c_cnt, s_cnt = 0, 0, 0, 0\n",
            "    for i, s in enumerate(sts):\n",
            "        st = str(s).lower()\n",
            "        if \"handwritten\" in st or \"user_note\" in st:\n",
            "            idx_pool.extend([i] * NOTE_WEIGHT)\n",
            "            n_cnt += NOTE_WEIGHT\n",
            "        elif \"exam\" in st or \"coursework\" in st or \"mcq\" in st:\n",
            "            idx_pool.extend([i] * EXAM_WEIGHT)\n",
            "            e_cnt += EXAM_WEIGHT\n",
            "        elif \"constitutional\" in st or \"judgment\" in st or \"rule\" in st or \"theories\" in st:\n",
            "            idx_pool.extend([i] * COURT_WEIGHT)\n",
            "            c_cnt += COURT_WEIGHT\n",
            "        else:\n",
            "            idx_pool.append(i)\n",
            "            s_cnt += 1\n",
            "    random.seed(3407)\n",
            "    random.shuffle(idx_pool)\n",
            "    dataset = dataset.select(idx_pool)\n",
            "    total = len(dataset)\n",
            "    print(f'✅ 加權平衡完成！加權後訓練總樣本數：{total:,} 筆')\n",
            "    print(f'   - 📝 手寫筆記佔比：{n_cnt/total*100:.2f}% ({n_cnt:,} 次曝光)')\n",
            "    print(f'   - 🎓 司律真題/講義佔比：{e_cnt/total*100:.2f}% ({e_cnt:,} 次曝光)')\n",
            "    print(f'   - 🏛️ 憲法/裁判規準佔比：{c_cnt/total*100:.2f}% ({c_cnt:,} 次曝光)')\n",
            "    print(f'   - 📚 基礎模板語料佔比：{s_cnt/total*100:.2f}% ({s_cnt:,} 次曝光)')\n",
            "\n",
            "def formatting_prompts_func(examples):\n",
            "    instructions = examples[\"instruction\"]\n",
            "    inputs = examples[\"input\"]\n",
            "    outputs = examples[\"output\"]\n",
            "    texts = []\n",
            "    for instruction, inp, output in zip(instructions, inputs, outputs):\n",
            "        text = (\n",
            "            f\"<|im_start|>system\\n你是一位具備多年命題閱卷經驗之台灣司法官律師考試閱卷委員與法學權威。<|im_end|>\\n\"\n",
            "            f\"<|im_start|>user\\n{instruction}\\n{inp}<|im_end|>\\n\"\n",
            "            f\"<|im_start|>assistant\\n{output}<|im_end|>\"\n",
            "        )\n",
            "        texts.append(text)\n",
            "    return { \"text\": texts }\n",
            "\n",
            "dataset = dataset.map(formatting_prompts_func, batched=True)\n",
            "print(f'成功載入並格式化 {len(dataset):,} 筆微調樣本！')\n"
        ]
        break

with open(nb_path, "w", encoding="utf-8") as f:
    json.dump(nb, f, indent=2, ensure_ascii=False)

print("✅ train_colab.ipynb successfully updated with weighted dataset controls!")
