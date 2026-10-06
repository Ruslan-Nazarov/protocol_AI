"""Descriptive detector metrics over an explicit, finite reference corpus.

No independence assumption, confidence estimate, or latent model-use inference.
Unknown labels, outcomes and costs remain visible rather than becoming zeroes.
"""
import math


def number(value, name):
    if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0):
        raise ValueError(name+' must be a finite nonnegative number or null')


def summarize(records, universe):
    if not isinstance(records,list) or not isinstance(universe,list) or not universe or any(not isinstance(x,str) or not x for x in universe) or len(set(universe))!=len(universe):
        raise ValueError('Explicit unique nonempty corpus IDs required')
    counts=dict(tp=0,fn=0,fp=0,tn=0,unknown_reference=0,unknown_detection=0,
                violations=0,correct_cases=0,admitted=0,rejected=0,unknown_admission=0,
                task_success=0,task_failure=0,task_unknown=0)
    seen=set();covered=set();delays=[];delay_unknown=0;censored=0;costs=[];latencies=[];clusters=set()
    fields={'run_id','case_id','cluster_id','reference_origin','violation','detected','admitted',
            'task_success','violation_at_ms','detected_at_ms','cost_usd','latency_ms'}
    for row in records:
        if not isinstance(row,dict) or set(row)!=fields:raise ValueError('Unknown or missing record fields')
        for key in ('run_id','case_id','cluster_id','reference_origin'):
            if not isinstance(row[key],str) or not row[key].strip():raise ValueError('Missing '+key)
        if row['case_id'] not in universe:raise ValueError('Case outside declared corpus')
        key=(row['run_id'],row['case_id'])
        if key in seen:raise ValueError('Duplicate run/case observation')
        seen.add(key);covered.add(row['case_id']);clusters.add(row['cluster_id'])
        for key in ('violation','detected','admitted','task_success'):
            if row[key] is not None and type(row[key]) is not bool:raise ValueError('Boolean or null required: '+key)
        for key in ('violation_at_ms','detected_at_ms','cost_usd','latency_ms'):number(row[key],key)
        expected,detected=row['violation'],row['detected']
        if row['detected_at_ms'] is not None and detected is not True:raise ValueError('Detection time without detection')
        if row['violation_at_ms'] is not None and expected is not True:raise ValueError('Violation time without known violation')
        if expected is None:counts['unknown_reference']+=1
        else:
            counts['violations' if expected else 'correct_cases']+=1
            if detected is None:counts['unknown_detection']+=1
            else:counts[('tp' if detected else 'fn') if expected else ('fp' if detected else 'tn')]+=1
        counts['unknown_admission' if row['admitted'] is None else 'admitted' if row['admitted'] else 'rejected']+=1
        counts['task_unknown' if row['task_success'] is None else 'task_success' if row['task_success'] else 'task_failure']+=1
        if expected is True:
            if detected is True:
                if row['violation_at_ms'] is None or row['detected_at_ms'] is None:delay_unknown+=1
                else:
                    delay=row['detected_at_ms']-row['violation_at_ms']
                    if delay<0:raise ValueError('Detection precedes violation')
                    delays.append(delay)
            else:censored+=1
        if row['cost_usd'] is not None:costs.append(row['cost_usd'])
        if row['latency_ms'] is not None:latencies.append(row['latency_ms'])
    def rate(n,d):return {'numerator':n,'denominator':d,'value':n/d if d else None}
    return {'schema_version':1,'scope':'declared_corpus_only','records':len(records),'counts':counts,
            'miss_rate':rate(counts['fn'],counts['tp']+counts['fn']),
            'false_alarm_rate':rate(counts['fp'],counts['fp']+counts['tn']),
            'decision_coverage':rate(counts['tp']+counts['fn']+counts['fp']+counts['tn'],counts['violations']+counts['correct_cases']),
            'case_coverage':rate(len(covered),len(universe)),'unobserved_cases':sorted(set(universe)-covered),
            'delay_ms':{'observed':len(delays),'mean':sum(delays)/len(delays) if delays else None,
                        'unknown_for_detected':delay_unknown,'undetected_or_unknown':censored},
            'cost_usd':{'known_subtotal':sum(costs),'unknown_records':len(records)-len(costs),
                        'total':sum(costs) if len(costs)==len(records) and records else None},
            'latency_ms':{'observed':len(latencies),'mean':sum(latencies)/len(latencies) if latencies else None},
            'clusters':len(clusters),'independence_assumed':False,'uncertainty_reduction':None,
            'reference_origins':sorted({r['reference_origin'] for r in records})}
