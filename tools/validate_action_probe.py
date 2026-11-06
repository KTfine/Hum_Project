"""Check actual model-driven avatar states against spoken test intentions."""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path


def validate(directory, profile):
    events = [json.loads(line) for line in (directory / 'effect-probe.jsonl').read_text(encoding='utf-8').splitlines()]
    result = json.loads((directory / 'effect-state.json').read_text(encoding='utf-8'))
    inputs = [e for e in events if e.get('event') == 'gateway.send' and e.get('message', {}).get('type') == 'input.append']
    start = datetime.fromisoformat(inputs[0]['timestamp'])
    applied = [dict(e, seconds=(datetime.fromisoformat(e['timestamp']) - start).total_seconds()) for e in events if e.get('event') == 'command.applied']
    if profile == 'baseline':
        cases = [
            ('left_and_smile', 3, 25, {'x': 0.4, 'sprite_id': 'smile', 'y': 0.95, 'scale': 1.0, 'rotation': 0.0}),
            ('center_and_normal', 25, 40, {'x': 0.5, 'sprite_id': 'normal', 'y': 0.95, 'scale': 1.0, 'rotation': 0.0}),
        ]
    else:
        cases = [
            ('right_and_surprised', 3, 23, {'x_min': 0.55, 'sprite_id': 'surprised', 'y': 0.95, 'scale': 1.0, 'rotation': 0.0}),
            ('half_size', 23, 43, {'scale': 0.5, 'sprite_id': 'surprised', 'y': 0.95, 'rotation': 0.0}),
            ('rotate_fifteen', 43, 63, {'rotation': 15.0, 'scale': 0.5, 'sprite_id': 'surprised', 'y': 0.95}),
            ('quarter_and_happy', 63, 83, {'x': 0.25, 'sprite_id': 'happy', 'y': 0.95, 'scale': 0.5, 'rotation': 15.0}),
            ('reset_all', 83, 108, {'x': 0.5, 'sprite_id': 'normal', 'y': 0.95, 'scale': 1.0, 'rotation': 0.0}),
            ('negated_actions', 108, 128, {'x': 0.5, 'sprite_id': 'normal', 'y': 0.95, 'scale': 1.0, 'rotation': 0.0}),
        ]
    checks = []
    previous_state = None
    for name, begin, end, expected in cases:
        sampled = [s for s in result['states'] if begin <= s['second'] < end]
        state = sampled[-1] if sampled else {}
        commands = [e for e in applied if begin <= e['seconds'] < end]
        failures = []
        for key, wanted in expected.items():
            if key == 'x_min':
                matches = state.get('x', -1) >= wanted
            elif isinstance(wanted, str):
                matches = state.get(key) == wanted
            else:
                matches = key in state and math.isclose(state[key], wanted, abs_tol=0.001)
            if not matches:
                failures.append(f'{key}: expected {wanted}, observed {state.get(key)}')
        if name in {'half_size', 'rotate_fifteen'} and previous_state:
            if not math.isclose(state.get('x', -1), previous_state['x'], abs_tol=0.001):
                failures.append('unrequested horizontal movement')
        if name == 'negated_actions' and commands:
            failures.append('an action was executed despite negation')
        elif name != 'negated_actions' and not commands:
            failures.append('no model command was executed')
        checks.append({'case': name, 'passed': not failures, 'failures': failures, 'observed': state,
                       'commands': [e['command'] for e in commands],
                       'first_command_seconds_from_utterance_start': round(commands[0]['seconds'] - begin, 3) if commands else None})
        previous_state = state
    raw_text = ''.join(e['message'].get('text', '') for e in events if e.get('message', {}).get('kind') == 'text')
    errors = [e for e in events if e.get('message', {}).get('type') == 'error' or e.get('event') == 'command.skipped']
    summary = {'profile': profile, 'session_id': result['session_id'], 'input_chunks': len(inputs),
               'passed_cases': sum(c['passed'] for c in checks), 'total_cases': len(checks),
               'applied_command_count': len(applied), 'errors': len(errors), 'model_text': raw_text,
               'checks': checks}
    (directory / 'action-validation.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--profile', choices=['baseline', 'generalization'], default='generalization')
    args = parser.parse_args()
    summary = validate(args.directory, args.profile)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(0 if summary['passed_cases'] == summary['total_cases'] and not summary['errors'] else 1)
