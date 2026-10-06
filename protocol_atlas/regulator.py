"""Executable experimental interpretations of C/D; no writes to the protocol."""
from copy import deepcopy

POLICIES = {
    'increase': {'probe_only': 'Три успеха разрешают пробу; C растёт только после успешной пробы.',
                 'series_and_probe': 'C растёт после серии; отдельная успешная проба может дать второе повышение.'},
    'load': {'sum': 'Базовая нагрузка и надбавка сохраняются; итог может превышать 12.',
             'clamp': 'Итог ограничивается 12; исходная сумма также показывается.'},
    'recovery': {'restore_previous': 'После двух успехов с проверкой человеком восстановить прежний D.',
                 'restart_one': 'После двух успехов с проверкой человеком установить D=1.'},
    'model_change': {'reset': 'Новая модель начинает с C=4, D=1.',
                     'halve': 'Высокий профиль уменьшается вдвое; ниже старта применяются стартовые значения.'},
}
RECOMMENDED = {'increase': 'probe_only', 'load': 'sum', 'recovery': 'restart_one', 'model_change': 'reset'}


def simulate(payload):
    policy = payload.get('policy')
    if not isinstance(policy, dict) or any(policy.get(key) not in choices for key, choices in POLICIES.items()):
        raise ValueError('Нужно явно выбрать трактовку каждой из четырёх неоднозначностей.')
    supplied = payload.get('profile', {})
    if not isinstance(supplied, dict):
        raise ValueError('Нужен профиль C/D.')
    profile = {**{'C': 4, 'D': 1, 'series': 0, 'silent': False, 'recovery_successes': 0,
                  'previous_D': 1, 'probe_pending': False}, **supplied}
    for key, minimum, maximum in (('C', 1, 12), ('D', 0, 3), ('series', 0, 2),
                                 ('previous_D', 0, 3), ('recovery_successes', 0, 1)):
        if type(profile[key]) is not int or not minimum <= profile[key] <= maximum:
            raise ValueError('C: 1–12, D: 0–3, серия: 0–2; недопустимый профиль.')
    if any(type(profile[key]) is not bool for key in ('silent', 'probe_pending')):
        raise ValueError('Флаги профиля должны быть логическими.')
    factors = payload.get('factors', {'V': 0, 'L': 0, 'H': 0, 'N': 0})
    if not isinstance(factors, dict) or any(type(factors.get(key)) is not int or not 0 <= factors[key] <= 3 for key in ('V', 'L', 'H', 'N')):
        raise ValueError('Каждый фактор V/L/H/N должен быть целым числом 0–3.')
    bonus = payload.get('exact_count_bonus', 0)
    if type(bonus) is not int or bonus not in (0, 1, 2):
        raise ValueError('Надбавка за точный счёт: 0, 1 или 2.')
    base = sum(factors[key] for key in ('V', 'L', 'H', 'N'))
    raw = base + bonus
    load = min(12, raw) if policy['load'] == 'clamp' else raw
    external = payload.get('external_or_irreversible', False)
    if type(external) is not bool:
        raise ValueError('Признак внешнего действия должен быть логическим.')
    effective_D = min(profile['D'], 1) if external else profile['D']
    requested_depth = payload.get('decision_depth', 0)
    if type(requested_depth) is not int or not 0 <= requested_depth <= 3:
        raise ValueError('Глубина решения: 0–3.')
    gate = 'split' if load > profile['C'] else 'decision' if requested_depth > effective_D else 'execute'
    events = payload.get('events', [])
    if not isinstance(events, list) or len(events) > 100 or any(not isinstance(event, dict) for event in events):
        raise ValueError('Допускается до 100 событий.')
    history = []
    for event in events:
        before, reason, outcome = deepcopy(profile), '', event.get('type')
        if outcome not in ('success', 'error', 'silent_error', 'probe_success', 'model_change'):
            raise ValueError('Неизвестный тип события регулятора.')
        if outcome in ('success', 'probe_success'):
            if any(type(event.get(key, default)) is not bool for key, default in (
                    ('a_applicable', True), ('a_passed', False), ('b_planned', True), ('b_passed', False), ('second_model_only', False))):
                raise ValueError('Исходы проверок должны быть логическими.')
            issues = event.get('unresolved_c_issues', 0)
            if type(issues) is not int or issues < 0:
                raise ValueError('Число неснятых замечаний должно быть неотрицательным.')
            if event.get('second_model_only') or (not event.get('a_applicable', True) and not event.get('b_passed', False)):
                history.append({'before': before, 'after': deepcopy(profile), 'event': event,
                                'outcome': 'blocked', 'reason': 'Одна проверка вторым ИИ не даёт права менять C/D.'})
                continue
            if (event.get('a_applicable', True) and not event.get('a_passed', False)) or (event.get('b_planned', True) and not event.get('b_passed', False)) or issues:
                outcome, reason = 'error', 'Заявленный успех не прошёл применимые проверки.'
            elif outcome == 'probe_success' and (not profile['probe_pending'] or not event.get('a_passed') or not event.get('b_passed')):
                history.append({'before': before, 'after': deepcopy(profile), 'event': event,
                                'outcome': 'blocked', 'reason': 'Для пробы нужны разрешённая проба и проверки A+B.'})
                continue
        if outcome == 'model_change':
            profile.update(C=max(4, profile['C'] // 2) if policy['model_change'] == 'halve' else 4,
                           D=max(1, profile['D'] // 2) if policy['model_change'] == 'halve' else 1,
                           series=0, silent=False, recovery_successes=0, probe_pending=False)
            reason = 'Смена модели по явно выбранной экспериментальной политике.'
        elif outcome in ('error', 'silent_error'):
            profile.update(C=max(1, profile['C'] // 2), series=0, probe_pending=False, recovery_successes=0)
            if outcome == 'silent_error':
                if not profile['silent']:
                    profile['previous_D'] = profile['D']
                profile.update(D=0, silent=True)
            else:
                profile['D'] = max(0, profile['D'] - 1)
            reason = reason or 'Ошибка уменьшила нагрузку и самостоятельность.'
        else:
            if profile['silent']:
                profile['recovery_successes'] = profile['recovery_successes'] + 1 if event.get('b_passed') else 0
                if profile['recovery_successes'] >= 2:
                    profile.update(D=profile['previous_D'] if policy['recovery'] == 'restore_previous' else 1,
                                   silent=False, recovery_successes=0)
            if outcome == 'probe_success':
                profile.update(C=min(12, profile['C'] + 1), series=0, probe_pending=False)
                reason = 'Успешная усиленная проба: одно повышение C.'
            else:
                profile['series'] += 1
                if profile['series'] >= 3:
                    profile.update(series=0, probe_pending=profile['C'] < 12)
                    if policy['increase'] == 'series_and_probe':
                        profile['C'] = min(12, profile['C'] + 1)
                    if event.get('b_passed') and not profile['silent']:
                        profile['D'] = min(3, profile['D'] + 1)
                    reason = 'Серия завершена; дальнейшее повышение C зависит от выбранной трактовки.'
                else:
                    reason = 'Сохранён успешный шаг.'
        history.append({'before': before, 'after': deepcopy(profile), 'event': event, 'outcome': outcome, 'reason': reason})
    return {'status': 'experimental', 'policy': policy, 'load': {'base': base, 'bonus': bonus, 'raw': raw, 'effective': load},
            'effective_D_for_step': effective_D, 'gate': gate, 'profile': profile, 'history': history,
            'limits': 'Исполнение выбранных трактовок в симуляторе. PROTOCOL.md и CALIBRATION.md не изменены. Числа нагрузки — заданные оценки, не измерение внимания.'}
