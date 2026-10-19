"""Assess new review checks on saved outputs, without claiming fresh inference."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.artifacts import load_profile
from app.domain import Ticket
from app.quality import VERSION, review_findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'ml/artifacts/v2-checks-replay.json')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output filename; existing evidence is preserved')
    _, adapter = load_profile('models/v2.json')
    files = list(adapter.parent.glob('validation-*.jsonl'))
    if len(files) != 1:
        parser.error('Expected exactly one saved validation file in the v2 export')
    rows = [json.loads(line) for line in files[0].read_text().splitlines() if line.strip()]
    findings, counts = [], Counter()
    for row in rows:
        if row['variant'] != 'adapter': continue
        try:
            ticket = Ticket.model_validate_json(row['output']); ticket.check_source(row['report'])
        except ValueError:
            counts['invalid_saved_output'] += 1
            findings.append({'id': row['id'], 'status': 'rejected_invalid_saved_output'})
            continue
        checks = review_findings(ticket, row['report'])
        counts['valid_saved_output'] += 1
        counts.update(item['code'] for item in checks['findings'])
        findings.append({'id': row['id'], 'status': 'requires_human_review', 'checks': checks})
    result = {'mode': 'saved_unconstrained_output_replay', 'fresh_generation_performed': False,
              'review_checks_version': VERSION, 'counts': dict(counts), 'results': findings}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2); handle.write('\n')
    print(json.dumps(result['counts'], indent=2))
    print('Replay evidence:', args.output)


if __name__ == '__main__':
    main()
