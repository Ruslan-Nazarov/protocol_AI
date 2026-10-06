"""Explicit stage dependencies and current, human-reviewed input results."""
import re


def validate_plan(stages):
    if not isinstance(stages, list) or not 1 <= len(stages) <= 30:
        raise ValueError('В схеме должно быть 1–30 этапов.')
    result = {}
    for stage in stages:
        if not isinstance(stage, dict) or set(stage) != {'id','title','requires'} or not isinstance(stage['id'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', stage['id']) or stage['id'] in result:
            raise ValueError('Каждый этап должен иметь уникальный идентификатор, название и зависимости.')
        if not isinstance(stage['title'], str) or not stage['title'].strip() or len(stage['title']) > 1000 or not isinstance(stage['requires'], list) or len(stage['requires']) > 30 or any(not isinstance(i, str) for i in stage['requires']):
            raise ValueError('Нужно непустое название и список входных этапов.')
        result[stage['id']] = stage
    visited, order = set(), []
    def visit(ident, trail):
        if ident in trail:
            raise ValueError('Цикл этапов: '+' → '.join([*trail, ident]))
        if ident in visited:
            return
        for dep in result[ident]['requires']:
            if dep not in result:
                raise ValueError('Отсутствует входной этап '+dep)
            visit(dep, [*trail, ident])
        visited.add(ident)
        order.append(ident)
    for ident in result:
        visit(ident, [])
    return [result[i] for i in order]


def plan_state(plan, tasks, changed):
    stages = []
    latest = {}
    for task in sorted(tasks, key=lambda t: t.get('created_at','')):
        link = task.get('plan') or {}
        if link.get('id') == plan['id'] and link.get('revision') == plan['revision']:
            latest[link['stage_id']] = task
    for stage in plan['stages']:
        task = latest.get(stage['id'])
        blockers = []
        for dep in stage['requires']:
            source = latest.get(dep)
            if not source or (source.get('review') or {}).get('outcome') != 'accepted':
                blockers.append('Не принят результат этапа '+dep)
            elif source.get('checks', {}).get('blocking') or changed(source):
                blockers.append('Результат этапа '+dep+' требует повторной проверки.')
        status = ('needs_recheck' if task and changed(task) else
                  'accepted' if task and (task.get('review') or {}).get('outcome') == 'accepted' else
                  'running' if task and task['status'] == 'running' else
                  'awaiting_review' if task and task['status'] == 'awaiting_review' else
                  'blocked' if blockers else 'ready')
        stages.append({**stage, 'status': status, 'blockers': blockers, 'task_id': task['id'] if task else None,
                       'inputs': [latest[dep]['id'] for dep in stage['requires'] if dep in latest]})
    return {**plan, 'stages': stages, 'limits': 'Порядок проверен по явным зависимостям; достаточность схемы оценивает человек.'}
