"""Persist actual quota observations; token counters are never converted to quota."""
import datetime as dt
from pathlib import Path
import sqlite3
from contextlib import closing


def epoch(value):
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        return float(value)
    try:
        return dt.datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    except (ValueError,AttributeError,TypeError):
        return None


def record_payload(root,payload):
    time=epoch(payload.get('snapshotAt'))
    if time is None:
        return
    rates=payload.get('rate_limits') or {}
    samples=[]
    for key in ('five_hour','seven_day'):
        item=rates.get(key) or {}
        used=item.get('used_percentage')
        if not isinstance(used,(int,float)) or isinstance(used,bool) or not 0<=used<=100:
            continue
        samples.append((time,key,100-used,epoch(item.get('resets_at'))))
    if not samples:
        return
    folder=Path(root)/'.local'
    folder.mkdir(exist_ok=True)
    with closing(sqlite3.connect(folder/'quota-history.sqlite3',timeout=.5)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS samples (time REAL, window TEXT, remaining REAL, reset REAL, PRIMARY KEY(time,window))')
        for sample in samples:
            previous=db.execute('SELECT time,remaining,reset FROM samples WHERE window=? ORDER BY time DESC LIMIT 1',(sample[1],)).fetchone()
            if previous and previous[1:]==sample[2:] and 0<=sample[0]-previous[0]<60:
                continue
            db.execute('INSERT OR IGNORE INTO samples VALUES (?,?,?,?)',sample)


def read_history(root,start,end):
    result={'five_hour':[],'seven_day':[]}
    path=Path(root)/'.local/quota-history.sqlite3'
    if not path.exists():
        return result
    with closing(sqlite3.connect(path,timeout=.5)) as db:
        rows=db.execute('SELECT time,window,remaining,reset FROM samples WHERE time>=? AND time<=? ORDER BY time',(start,end))
        for time,window,remaining,reset in rows:
            if window in result:
                result[window].append({'time':time,'remaining':remaining,'reset':reset})
    return result

