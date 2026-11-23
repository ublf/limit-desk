import tempfile,unittest
from pathlib import Path
from quota_history import record_payload,read_history

class QuotaHistoryTests(unittest.TestCase):
    def test_records_actual_remaining_and_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            record_payload(folder,{'snapshotAt':1000,'rate_limits':{'five_hour':{'used_percentage':40,'resets_at':2000},'seven_day':{'used_percentage':100,'resets_at':3000}}})
            result=read_history(folder,0,2000)
        self.assertEqual(result['five_hour'],[{'time':1000,'remaining':60,'reset':2000}])
        self.assertEqual(result['seven_day'][0]['remaining'],0)
    def test_deduplicate_same_value_but_keep_changes_and_minute_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            for stamp,used in [(1000,20),(1001,20),(1010,25),(1020,25),(1070,25)]:
                record_payload(folder,{'snapshotAt':stamp,'rate_limits':{'five_hour':{'used_percentage':used,'resets_at':3000}}})
            result=read_history(folder,0,2000)
        self.assertEqual([p['time'] for p in result['five_hour']],[1000,1010,1070])
        self.assertEqual([p['remaining'] for p in result['five_hour']],[80,75,75])
    def test_no_synthesized_history_or_invalid_values(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(read_history(folder,0,2000)['five_hour'],[])
            for used in [None,True,-1,101,float('nan')]:
                record_payload(folder,{'snapshotAt':1000,'rate_limits':{'five_hour':{'used_percentage':used}}})
            self.assertEqual(read_history(folder,0,2000)['five_hour'],[])
    def test_missing_timestamp_does_not_become_current_time(self):
        with tempfile.TemporaryDirectory() as folder:
            record_payload(folder,{'rate_limits':{'five_hour':{'used_percentage':25}}})
            self.assertEqual(read_history(folder,0,9999999999)['five_hour'],[])

if __name__=='__main__':unittest.main()
