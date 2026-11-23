"""Read local Claude usage counters. Never expose message bodies or tool arguments."""
from collections import Counter
import datetime as dt
import json
from pathlib import Path

FIELDS = ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')

def timestamp(value):
    try:
        return dt.datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    except (ValueError, AttributeError):
        return None


def analyze(projects, start, end):
    requests = {}
    files = [p for p in Path(projects).rglob('*.jsonl') if p.stat().st_mtime >= start]
    # Prefer a subagent's own log over a mirrored parent event.
    files.sort(key=lambda p: ('subagents' not in p.parts, str(p)))
    for path in files:
        relative = path.relative_to(projects)
        project = relative.parts[0]
        agent = 'subagents' in relative.parts
        session = relative.parts[1] if agent else path.stem
        source = (project,session,path.stem,agent)
        calls={}; result_ids=set(); tool_results=[]
        try:
            with path.open(encoding='utf-8',errors='replace') as stream:
                for line in stream:
                    try:
                        event=json.loads(line)
                    except ValueError:
                        continue
                    event_time=timestamp(event.get('timestamp'))
                    if event.get('type') == 'user' and event_time is not None and start <= event_time <= end:
                        content=(event.get('message') or {}).get('content',[])
                        if isinstance(content,list):
                            for block in content:
                                if not isinstance(block,dict) or block.get('type')!='tool_result':
                                    continue
                                tool_id=block.get('tool_use_id')
                                if not tool_id or tool_id in result_ids:
                                    continue
                                result_ids.add(tool_id)
                                value=block.get('content','')
                                size=len(value) if isinstance(value,str) else len(json.dumps(value,ensure_ascii=False))
                                tool_results.append((tool_id,size))
                    if event.get('type') != 'assistant':
                        continue
                    message=event.get('message') or {}
                    usage=message.get('usage')
                    id=message.get('id')
                    time=timestamp(event.get('timestamp'))
                    if not id or not isinstance(usage,dict) or time is None or not start <= time <= end or message.get('model','').startswith('<'):
                        continue
                    record=requests.setdefault(id,{'source':source,'time':time,'model':message.get('model','unknown'),'tokens':dict.fromkeys(FIELDS,0),'tools':{},'thinking':0,'context':0,'cwd':Path(event.get('cwd') or project).name})
                    record['time']=min(record['time'],time)
                    for field in FIELDS:
                        value=usage.get(field,0)
                        if isinstance(value,(int,float)) and value>=0:
                            record['tokens'][field]=max(record['tokens'][field],int(value))
                    thinking=(usage.get('output_tokens_details') or {}).get('thinking_tokens',0)
                    if isinstance(thinking,(int,float)):
                        record['thinking']=max(record['thinking'],thinking)
                    for block in message.get('content',[]):
                        if isinstance(block,dict) and block.get('type')=='tool_use' and block.get('id'):
                            record['tools'][block['id']]=block.get('name','unknown')
                            tool_input=block.get('input') or {}
                            name=Path(tool_input.get('file_path') or '').name
                            calls[block['id']]={'name':block.get('name','unknown'),'file':name}
        except OSError:
            continue
        for id,size in tool_results:
            if id in calls:
                for record in requests.values():
                    if record['source']==source and id in record['tools']:
                        record.setdefault('results',[]).append({**calls[id],'characters':size})
                        break
    groups={}; buckets={}; models={}
    def add(target,record):
        target['requests']+=1
        for key in FIELDS:
            target[key]+=record['tokens'][key]
        target['thinking']+=record['thinking']
    def blank():
        return {'requests':0,**dict.fromkeys(FIELDS,0),'thinking':0}
    for record in requests.values():
        project,session,file,agent=record['source']
        group=groups.setdefault(record['source'],{**blank(),'project':record['cwd'],'session':session,'agent':file if agent else None,'models':set(),'tools':Counter(),'first':record['time'],'last':record['time'],'peakContext':0,'largestReads':[]})
        add(group,record)
        group['largestReads'].extend(r for r in record.get('results',[]) if r['name']=='Read' and r['file'])
        group['models'].add(record['model'])
        group['tools'].update(record['tools'].values())
        group['first']=min(group['first'],record['time']);group['last']=max(group['last'],record['time'])
        group['peakContext']=max(group['peakContext'],sum(record['tokens'][k] for k in FIELDS if k!='output_tokens'))
        bucket=int(record['time']//300)*300
        add(buckets.setdefault(bucket,blank()),record)
        add(models.setdefault(record['model'],blank()),record)
    total=blank()
    for record in requests.values(): add(total,record)
    for group in groups.values():
        group['largestReads']=sorted(group['largestReads'],key=lambda r:r['characters'],reverse=True)[:5]
        group['models']=sorted(group['models'])
        group['tools']=dict(group['tools'].most_common())
        group['totalTokens']=sum(group[k] for k in FIELDS)
    return {'start':start,'end':end,'totals':total,'groups':sorted(groups.values(),key=lambda g:g['totalTokens'],reverse=True),'models':[{'model':model,**data} for model,data in models.items()], 'timeline':[{'time':time,**data} for time,data in sorted(buckets.items())], 'filesScanned':len(files)}
