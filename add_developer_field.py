import json, sys, pathlib
manifest_path = pathlib.Path('data/drive_notes_manifest.json')
if not manifest_path.is_file():
    print('manifest not found')
    sys.exit(1)
with manifest_path.open('r', encoding='utf-8') as f:
    data = json.load(f)
# add developer field if missing
for entry in data:
    entry.setdefault('developer', 'LawExamData Team')
with manifest_path.open('w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print('Added developer field to', len(data), 'entries')
