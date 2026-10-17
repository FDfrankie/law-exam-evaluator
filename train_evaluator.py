"""
Taiwan Law Examination Evaluator SFT Fine-Tuning Pipeline
Trains on verified authentic judicial reasoning and scoring rubric dataset:
G:\\我的雲端硬碟\\LawExamData\\training_data\\law_exam_verified_sft.jsonl
Supports both local execution (CPU / GPU) and Google Colab cloud execution.
All console logs in pure ASCII to ensure 100% stability under Windows cp950 shell.
"""
import os
import sys
import argparse
import json
import time
from pathlib import Path

# Windows console encoding safeguard
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import torch
from torch.utils.data import Dataset, DataLoader
from transformers import AutoTokenizer, AutoModelForCausalLM, get_linear_schedule_with_warmup

from config import DATA_DIR

DEFAULT_DATASET = Path(DATA_DIR) / "training_data" / "law_exam_verified_sft.jsonl"
DEFAULT_OUTPUT_DIR = Path(DATA_DIR) / "checkpoints" / "law_evaluator_qwen"

class LawExamSFTDataset(Dataset):
    def __init__(self, data_path: Path, tokenizer, max_length: int = 1024, max_samples: int = None):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.samples = []

        print(f"  [DATASET] Loading verified legal SFT records from {data_path.name}...")
        count = 0
        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    item = json.loads(line_str)
                except Exception:
                    continue
                instruction = item.get("instruction", "")
                inp = item.get("input", "")
                output = item.get("output", "")

                if not (instruction and output):
                    continue

                # Standard ChatML format for Qwen / modern instruction models
                prompt = (
                    f"<|im_start|>system\n"
                    f"你是一位具備多年命題閱卷經驗之台灣司法官律師考試閱卷委員與法學權威講座。<|im_end|>\n"
                    f"<|im_start|>user\n"
                    f"{instruction}\n{inp}<|im_end|>\n"
                    f"<|im_start|>assistant\n"
                )
                full_text = prompt + output + "<|im_end|>"
                self.samples.append(full_text)
                count += 1
                if max_samples and count >= max_samples:
                    break

        print(f"  [DATASET] Successfully loaded {len(self.samples):,} verified training samples.")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        text = self.samples[idx]
        enc = self.tokenizer(
            text,
            max_length=self.max_length,
            truncation=True,
            padding="max_length",
            return_tensors="pt"
        )
        input_ids = enc["input_ids"].squeeze(0)
        attention_mask = enc["attention_mask"].squeeze(0)
        # Labels are same as input_ids for Causal LM, pad tokens masked with -100
        labels = input_ids.clone()
        labels[labels == self.tokenizer.pad_token_id] = -100

        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "labels": labels
        }

def run_training(args):
    print("=" * 70)
    print("  Starting Taiwan Law Examination Evaluator SFT Fine-Tuning")
    print(f"  Base Model: {args.model_name}")
    print(f"  Dataset: {args.dataset}")
    print(f"  Target Checkpoints: {args.output_dir}")
    print(f"  Device: {'cuda' if torch.cuda.is_available() else 'cpu'}")
    print(f"  Batch Size: {args.batch_size} | Epochs: {args.epochs}")
    print("=" * 70)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[1/4] Loading Tokenizer and Model: {args.model_name}...")
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        torch_dtype=torch.float32 if device.type == "cpu" else torch.float16
    )
    model.to(device)

    print(f"\n[2/4] Preparing Dataset & DataLoader...")
    dataset = LawExamSFTDataset(
        data_path=args.dataset,
        tokenizer=tokenizer,
        max_length=args.max_length,
        max_samples=args.max_samples
    )
    dataloader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True)

    print(f"\n[3/4] Configuring Optimizer & Learning Rate Scheduler...")
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=0.01)
    total_steps = len(dataloader) * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=max(5, int(total_steps * 0.05)),
        num_training_steps=total_steps
    )

    print(f"\n[4/4] Starting Fine-Tuning Training Loop ({total_steps} total steps)...")
    model.train()
    start_time = time.time()

    global_step = 0
    running_loss = 0.0
    step_loss_count = 0

    for epoch in range(1, args.epochs + 1):
        print(f"\n--- Epoch {epoch}/{args.epochs} ---")
        for step, batch in enumerate(dataloader, start=1):
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["labels"].to(device)

            outputs = model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                labels=labels
            )
            loss = outputs.loss

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()

            global_step += 1
            running_loss += loss.item()
            step_loss_count += 1

            if global_step % args.log_interval == 0 or global_step == 1:
                avg_loss = running_loss / max(1, step_loss_count)
                elapsed = time.time() - start_time
                print(f"  Step [{global_step}/{total_steps}] | Loss: {avg_loss:.4f} | LR: {scheduler.get_last_lr()[0]:.2e} | Elapsed: {elapsed:.1f}s")
                running_loss = 0.0
                step_loss_count = 0

        # Save checkpoint after each epoch
        epoch_dir = args.output_dir / f"checkpoint-epoch-{epoch}"
        epoch_dir.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(epoch_dir)
        tokenizer.save_pretrained(epoch_dir)
        print(f"  [SAVED] Checkpoint saved: {epoch_dir}")

    # Save final model
    final_dir = args.output_dir / "final_model"
    final_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)

    total_time = time.time() - start_time
    print("\n" + "=" * 70)
    print("  [TRAINING COMPLETE]")
    print(f"  Total Steps Completed: {global_step}")
    print(f"  Total Duration: {total_time / 60:.2f} minutes")
    print(f"  Saved Final Model to: {final_dir}")
    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(description="Law Exam Evaluator Fine-Tuning")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Path to verified SFT jsonl dataset")
    parser.add_argument("--model_name", type=str, default="Qwen/Qwen2.5-0.5B-Instruct", help="Hugging Face base model name")
    parser.add_argument("--output_dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory to save model checkpoints")
    parser.add_argument("--epochs", type=int, default=1, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=2, help="Batch size per step")
    parser.add_argument("--max_length", type=int, default=512, help="Maximum sequence length")
    parser.add_argument("--learning_rate", type=float, default=3e-5, help="Learning rate")
    parser.add_argument("--max_samples", type=int, default=100, help="Max samples to train on for local CPU (set higher or None for full)")
    parser.add_argument("--log_interval", type=int, default=5, help="Logging step interval")

    args = parser.parse_args()
    run_training(args)

if __name__ == "__main__":
    main()
