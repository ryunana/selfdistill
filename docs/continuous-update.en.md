# Keep Your Profile Up to Date

English | [中文](continuous-update.md)

After the first distillation, choose the path that matches what changed instead of reprocessing all history every time.

## Path 1: Import a New Batch of Chats

Use this when you have a complete set of chats from a new period.

1. Follow [Import Sources](../README.en.md#import-sources) and use `import_chats.py` to normalize the new records into the local `input/` directory.
2. Follow [`prompts/distill.md`](../prompts/distill.md) to read the new material, report the boundary, and propose L1–L4 candidates without modifying `canonical/`.
3. Review every candidate and explicitly confirm the final aggregate diff before anything is written.
4. After writing, run `python3 build.py`. If you need to write back to an AI tool, confirm the `install.py --target ...` diff first.

## Path 2: Record a Few Day-to-Day Corrections

Use this for explicit corrections, wording mismatches, or boundary updates that appear in ordinary conversations.

1. Create one candidate JSON in `inbox/` following [`schemas/inbox-v2.json`](../schemas/inbox-v2.json). A candidate taken directly from a conversation may temporarily leave `evidence_ids` empty and use the `pending` status.
2. Run `python3 distill_audit.py audit` to generate the `reports/latest/` evidence pack. This command rebuilds that directory every time; review unfinished material first or save it outside the directory.
3. Give [`prompts/rediscovery.md`](../prompts/rediscovery.md) to the current AI and require it to read `reports/latest/evidence.md` in full. It may write findings and pending candidates only to `reports/`, never to `canonical/`.
4. Run `python3 distill_audit.py verify reports/latest` to check source drift, candidate structure, and evidence references.
5. Update `canonical/` only after human review, then run `python3 build.py`; any write-back to an AI tool still requires a confirmed diff.

## Boundaries

- `accepted` means a candidate was accepted; it does not mean the candidate has been written to `canonical/`.
- `verify` checks integrity, structure, and references. It does not judge whether a conclusion is correct or prove that the AI read all evidence.
- `input/`, real `inbox/*.json`, `reports/`, and `dist/` are git-ignored by default. Never commit real personal data.
- If you send evidence to a cloud AI, the submitted content remains subject to that provider's data policy.
