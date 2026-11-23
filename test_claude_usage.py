import json,time,tempfile,unittest,os
from pathlib import Path
from claude_usage import analyze

class UsageAnalysisTests(unittest.TestCase):
    def write(self, path, events):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('\n'.join(json.dumps(e) for e in events),encoding='utf-8')
        os.utime(path,(1893459600,1893459600))
    def event(self,id,output=10,model='claude-test',kind='assistant'):
        return {'type':kind,'timestamp':'2030-01-01T00:01:00Z','cwd':'C:/project','message':{'id':id,'model':model,'usage':{'input_tokens':2,'cache_creation_input_tokens':100,'cache_read_input_tokens':1000,'output_tokens':output,'output_tokens_details':{'thinking_tokens':3}},'content':[]}}
    def test_deduplicate_streaming_and_mirrored_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.write(root/'project/session/subagents/agent-a.jsonl',[self.event('one',5),self.event('one',10)])
            self.write(root/'project/session.jsonl',[self.event('one',10),self.event('two',20)])
            report=analyze(root,1893456000,1893459600)
        self.assertEqual(report['totals']['requests'],2)
        self.assertEqual(report['totals']['output_tokens'],30)
        self.assertEqual(report['totals']['cache_read_input_tokens'],2000)
        self.assertEqual(report['totals']['thinking'],6)
        self.assertEqual(len(report['groups']),2)
        self.assertEqual(report['groups'][0]['peakContext'],1102)
    def test_filter_by_time_and_skip_synthetic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            old=self.event('old');old['timestamp']='2020-01-01T00:00:00Z'
            self.write(root/'project/s.jsonl',[old,self.event('synthetic',model='<synthetic>'),self.event('real')])
            with (root/'project/s.jsonl').open('a') as f:f.write('\n{partial')
            os.utime(root/'project/s.jsonl',(1893459600,1893459600))
            report=analyze(root,1893456000,1893459600)
        self.assertEqual(report['totals']['requests'],1)
    def test_tool_result_size_is_not_counted_as_token_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            event=self.event('one')
            event['message']['content']=[{'type':'tool_use','id':'tool-1','name':'Read','input':{'file_path':'C:/private/large.sql','secret':'hidden'}}]
            result={'type':'user','timestamp':'2030-01-01T00:02:00Z','message':{'content':[{'type':'tool_result','tool_use_id':'tool-1','content':'sensitive text'}]}}
            self.write(root/'project/s.jsonl',[event,result,result])
            report=analyze(root,1893456000,1893459600)
        self.assertEqual(report['groups'][0]['largestReads'][0]['characters'],14)
        self.assertEqual(report['totals']['input_tokens'],2)
        self.assertNotIn('sensitive text',json.dumps(report))
        self.assertNotIn('hidden',json.dumps(report))
        self.assertNotIn('private',json.dumps(report))

if __name__=='__main__':unittest.main()

