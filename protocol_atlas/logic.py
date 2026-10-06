"""Explicit, bounded proof kernels. No model calls, eval, or automatic repair.

A certificate establishes derivability from the pinned premises, not their truth
or the fidelity of the source-to-formula translation. The caller must protect the
selection and enforce the admission result before consuming a conclusion.
"""
import copy
import hashlib
import json
from pathlib import Path
import re

PROFILES = {
    'syllogistic-universal-v1': {
        'name': 'Универсальный фрагмент силлогистики',
        'language': 'all(S,M), no(S,M); symbols denote classes',
        'semantics': 'Classes may be empty; no existential import or subalternation.',
        'rules': {
            'barbara': 'all(S,M), all(M,P) => all(S,P)',
            'celarent': 'all(S,M), no(M,P) => no(S,P)',
            'no_conversion': 'no(S,P) => no(P,S)',
        },
    },
    'classical-propositional-v1': {
        'name': 'Фрагмент классической логики высказываний',
        'language': 'atom, not(A), and(A,B), implies(A,B)',
        'semantics': 'Two-valued propositional semantics; explicit derivations only.',
        'rules': {
            'modus_ponens': 'A, implies(A,B) => B',
            'modus_tollens': 'implies(A,B), not(B) => not(A)',
            'and_intro': 'A, B => and(A,B)',
            'and_left': 'and(A,B) => A',
            'and_right': 'and(A,B) => B',
            'double_negation': 'not(not(A)) => A',
        },
    },
}
LIMITS = ('Checked: declared syntax, symbols, exact source excerpts and rule applications. '
          'Not checked: truth of premises, source authenticity, faithful natural-language '
          'formalization, external prose/actions, or protection of this checker from writes.')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def checker_version():
    # Also binds the runtime admission implementation, not only the proof kernel.
    base = Path(__file__).parent
    return sha(''.join(sha((base / name).read_text(encoding='utf-8'))
                       for name in ('logic.py', 'project_runtime.py')))


class Violation(ValueError):
    def __init__(self, code, where, detail):
        self.code, self.where, self.detail = code, where, detail
        super().__init__(f'{code} at {where}: {detail}')


def require(condition, code, where, detail):
    if not condition:
        raise Violation(code, where, detail)


def fields(value, expected, where):
    require(isinstance(value, dict) and set(value) == set(expected),
            'schema', where, 'Expected fields: '+', '.join(expected))


def label(value, where, limit=2000):
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= limit and '\0' not in value,
            'schema', where, 'Expected nonempty bounded text')


def ident(value, where):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,59}', value),
            'schema', where, 'Expected an ASCII identifier')


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_key', key, 'Duplicate JSON key')
            result[key] = value
        return result
    def constant(value):
        raise Violation('schema', '$', 'Non-finite JSON number: '+value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def formula(value, contract, where):
    symbols = {s['symbol'] for s in contract['symbols']}
    budget = [0]
    def walk(node, depth):
        budget[0] += 1
        require(depth <= 16 and budget[0] <= 128, 'formula_limit', where, 'Formula too large')
        if isinstance(node, str):
            require(node in symbols, 'symbol_drift', where,
                    'Undeclared symbol '+repr(node)+'; declared: '+', '.join(sorted(symbols)))
            return node
        require(isinstance(node, list) and len(node) in (2, 3) and isinstance(node[0], str),
                'formula_syntax', where, 'Expected a symbol or operator array')
        op = node[0]
        if contract['profile'] == 'syllogistic-universal-v1':
            require(depth == 0 and op in ('all', 'no') and len(node) == 3 and
                    all(isinstance(n, str) for n in node[1:]),
                    'formula_syntax', where, 'Expected [all|no, subject, predicate]')
        else:
            require(op in ('not', 'and', 'implies') and len(node) == (2 if op == 'not' else 3),
                    'formula_syntax', where, 'Unknown operator or arity for selected logic')
        return (op, *(walk(n, depth+1) for n in node[1:]))
    result = walk(value, 0)
    require(contract['profile'] != 'syllogistic-universal-v1' or isinstance(result, tuple),
            'formula_syntax', where, 'A syllogistic proposition needs an operator')
    return result


def validate_contract(contract):
    fields(contract, ('id', 'version', 'profile', 'scope', 'selection_reason', 'alternatives',
                      'enabled_rules', 'symbols', 'sources', 'premises'), 'contract')
    require(len(canonical(contract).encode('utf-8')) <= 100000, 'contract_limit', 'contract', '100000 bytes maximum')
    ident(contract['id'], 'contract.id')
    require(type(contract['version']) is int and contract['version'] > 0, 'schema', 'version', 'Positive integer')
    require(isinstance(contract['profile'], str) and contract['profile'] in PROFILES,
            'unsupported_profile', 'profile', 'Install and test a kernel before selecting its logic')
    label(contract['scope'], 'scope')
    label(contract['selection_reason'], 'selection_reason')
    require(isinstance(contract['alternatives'], list) and 1 <= len(contract['alternatives']) <= 10,
            'selection_missing', 'alternatives', 'Record at least one considered alternative')
    for alt in contract['alternatives']:
        fields(alt, ('profile', 'reason_not_selected'), 'alternative')
        label(alt['profile'], 'alternative.profile', 200)
        label(alt['reason_not_selected'], 'alternative.reason')
    rules = contract['enabled_rules']
    require(isinstance(rules, list) and 1 <= len(rules) <= 20 and all(isinstance(r, str) for r in rules),
            'schema', 'enabled_rules', 'Nonempty rule list')
    require(len(set(rules)) == len(rules) and set(rules) <= set(PROFILES[contract['profile']]['rules']),
            'unsupported_rule', 'enabled_rules', 'Only implemented rules of this profile are allowed')
    require(isinstance(contract['symbols'], list) and 1 <= len(contract['symbols']) <= 100,
            'schema', 'symbols', 'Declare 1–100 concepts')
    ids, names = set(), set()
    for symbol in contract['symbols']:
        fields(symbol, ('id', 'symbol', 'meaning'), 'symbol')
        ident(symbol['id'], 'symbol.id')
        ident(symbol['symbol'], 'symbol.symbol')
        label(symbol['meaning'], 'symbol.meaning')
        require(symbol['id'] not in ids and symbol['symbol'] not in names,
                'symbol_collision', 'symbols', 'Concept IDs and symbols must be unique within this scope')
        ids.add(symbol['id']); names.add(symbol['symbol'])
    require(isinstance(contract['sources'], dict) and len(contract['sources']) <= 50,
            'schema', 'sources', 'Source ID to exact text, at most 50')
    for ref, source in contract['sources'].items():
        ident(ref, 'source.id'); label(source, 'source.text', 20000)
    require(isinstance(contract['premises'], list) and 1 <= len(contract['premises']) <= 100,
            'schema', 'premises', 'Declare 1–100 premises')
    premises = set()
    for premise in contract['premises']:
        fields(premise, ('id', 'formula', 'basis'), 'premise')
        ident(premise['id'], 'premise.id')
        require(premise['id'] not in premises, 'duplicate_id', 'premise.id', premise['id'])
        premises.add(premise['id'])
        formula(premise['formula'], contract, premise['id'])
        basis = premise['basis']
        require(isinstance(basis, dict), 'schema', 'basis', 'Source or explicit assumption required')
        if basis.get('kind') == 'source':
            fields(basis, ('kind', 'ref', 'quote'), 'basis')
            ident(basis['ref'], 'basis.ref'); label(basis['quote'], 'basis.quote', 20000)
            require(basis['ref'] in contract['sources'] and basis['quote'] in contract['sources'][basis['ref']],
                    'source_mismatch', premise['id'], 'Exact excerpt absent from pinned source')
        else:
            fields(basis, ('kind', 'reason'), 'basis')
            require(basis['kind'] == 'assumption', 'schema', 'basis.kind', 'source or assumption')
            label(basis['reason'], 'basis.reason')
    return contract


def select(contract):
    contract = copy.deepcopy(validate_contract(contract))
    return {'contract': contract, 'sha256': sha(canonical(contract)), 'checker_sha256': checker_version()}


def apply_rule(rule, args):
    """Return the unique conclusion of a rule with ordered premises, or reject."""
    def isop(value, op):
        return isinstance(value, tuple) and value[0] == op
    if rule in ('barbara', 'celarent') and len(args) == 2:
        a, b = args
        op = 'all' if rule == 'barbara' else 'no'
        if isop(a, 'all') and isop(b, op) and a[2] == b[1]:
            return (op, a[1], b[2])
    if rule == 'no_conversion' and len(args) == 1 and isop(args[0], 'no'):
        return ('no', args[0][2], args[0][1])
    if rule == 'modus_ponens' and len(args) == 2 and isop(args[1], 'implies') and args[0] == args[1][1]:
        return args[1][2]
    if rule == 'modus_tollens' and len(args) == 2 and isop(args[0], 'implies') and args[1] == ('not', args[0][2]):
        return ('not', args[0][1])
    if rule == 'and_intro' and len(args) == 2:
        return ('and', *args)
    if rule in ('and_left', 'and_right') and len(args) == 1 and isop(args[0], 'and'):
        return args[0][1 if rule == 'and_left' else 2]
    if rule == 'double_negation' and len(args) == 1 and isop(args[0], 'not') and isop(args[0][1], 'not'):
        return args[0][1][1]
    raise Violation('invalid_rule_application', 'inputs', 'Premises do not match '+rule)


def render(value):
    if isinstance(value, str):
        return value
    op, *args = value
    if op == 'all':return f'Все {args[0]} являются {args[1]}.'
    if op == 'no':return f'Ни один {args[0]} не является {args[1]}.'
    if op == 'not':return '¬('+render(args[0])+')'
    return '('+render(args[0])+(' ∧ ' if op == 'and' else ' → ')+render(args[1])+')'


def verify(raw, selection):
    """Preserve the raw candidate, admit only fully checked formal conclusions."""
    report = {'status': 'fail', 'admitted': False, 'raw': raw, 'violations': [],
              'conclusions': [], 'answer': '', 'semantic_status': 'unverified', 'limits': LIMITS}
    try:
        require(isinstance(raw, str) and len(raw.encode('utf-8')) <= 64000,
                'candidate_limit', '$', 'Candidate must be a UTF-8 string up to 64000 bytes')
        report['raw_sha256'] = sha(raw)
        fields(selection, ('contract', 'sha256', 'checker_sha256'), 'selection')
        contract = validate_contract(selection['contract'])
        require(sha(canonical(contract)) == selection['sha256'], 'contract_changed', 'selection', 'Contract hash differs')
        require(checker_version() == selection['checker_sha256'], 'checker_changed', 'selection', 'Reselect and recheck with current checker')
        report.update(contract_sha256=selection['sha256'], checker_sha256=selection['checker_sha256'])
        candidate = strict_json(raw)
        fields(candidate, ('contract_sha256', 'scope', 'steps', 'conclusions'), '$')
        require(candidate['contract_sha256'] == selection['sha256'], 'stale_contract', 'contract_sha256', 'Wrong contract version')
        require(candidate['scope'] == contract['scope'], 'scope_drift', 'scope', 'Wrong scope')
        require(isinstance(candidate['steps'], list) and len(candidate['steps']) <= 100,
                'schema', 'steps', 'At most 100 proof steps')
        known = {p['id']: formula(p['formula'], contract, p['id']) for p in contract['premises']}
        dependencies = {p['id']: [p['id']] for p in contract['premises']}
        for index, step in enumerate(candidate['steps']):
            where = f'steps[{index}]'
            fields(step, ('id', 'rule', 'inputs', 'formula'), where)
            ident(step['id'], where+'.id')
            require(step['id'] not in known, 'duplicate_id', where, step['id'])
            require(isinstance(step['rule'], str) and step['rule'] in contract['enabled_rules'],
                    'rule_not_selected', where+'.rule', 'Rule not enabled by chosen logic')
            inputs = step['inputs']
            require(isinstance(inputs, list) and 1 <= len(inputs) <= 2 and all(isinstance(i, str) and i in known for i in inputs),
                    'missing_premise', where+'.inputs', 'Only earlier checked steps or pinned premises')
            actual = formula(step['formula'], contract, where+'.formula')
            try:
                expected = apply_rule(step['rule'], [known[i] for i in inputs])
            except Violation as exc:
                raise Violation(exc.code, where+'.inputs', exc.detail) from exc
            require(expected == actual, 'invalid_conclusion', where+'.formula', 'Expected '+render(expected)+'; got '+render(actual))
            known[step['id']] = actual
            dependencies[step['id']] = sorted({p for i in inputs for p in dependencies[i]})
        outputs = candidate['conclusions']
        require(isinstance(outputs, list) and 1 <= len(outputs) <= 100 and
                all(isinstance(i, str) and i in known for i in outputs) and len(set(outputs)) == len(outputs),
                'missing_conclusion', 'conclusions', 'Reference existing checked nodes exactly once')
        report['conclusions'] = [{'id': i, 'formula': known[i], 'premise_ids': dependencies[i],
                                  'text': render(known[i])} for i in outputs]
        report['answer'] = '\n'.join(c['text'] for c in report['conclusions'])
        report.update(status='pass', admitted=True)
    except (Violation, ValueError, TypeError, RecursionError) as exc:
        report['violations'].append({'code': getattr(exc, 'code', 'schema'),
                                     'where': getattr(exc, 'where', '$'),
                                     'detail': getattr(exc, 'detail', 'Malformed or excessively nested JSON')})
    return report


RESPONSE_INSTRUCTION = (
    'Return only JSON with contract_sha256, scope, steps, conclusions. '
    'Each step has id, rule, inputs (earlier node IDs), formula. '
    'Use only the pinned logic_selection contract and enabled rules. '
    'Formulas are arrays [operator, operands...] or declared atom strings. '
    'Do not change meanings, symbols, premises, scope, or contract. '
    'conclusions is a nonempty list of node IDs. No additional prose or fields. '
    'The checker renders the result and labels semantic grounding unverified.'
)
