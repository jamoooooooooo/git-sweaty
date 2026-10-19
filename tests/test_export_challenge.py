import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from export_challenge import decode_polyline, metrics, sample_points, needs_gps, local_date

class ChallengeExportTests(unittest.TestCase):
    def test_route_decode_uses_longitude_latitude(self):
        self.assertEqual(decode_polyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@'), [[-120.2,38.5],[-120.95,40.7],[-126.453,43.252]])
        with self.assertRaises(ValueError): decode_polyline('_')

    def test_original_endpoints_are_preserved_when_sampling(self):
        points=[[i / 100000, 30] for i in range(30000)]
        result=sample_points(points)
        self.assertLessEqual(len(result),12000)
        self.assertEqual(result[0],points[0]);self.assertEqual(result[-1],points[-1])

    def test_time_and_local_date_are_not_replaced_with_utc_date(self):
        activity={'id':42,'type':'Run','start_date_local':'2026-10-09T23:45:00','start_date':'2026-10-10T05:45:00Z','distance':3218.688,'moving_time':1000,'elapsed_time':1300}
        result=metrics(activity,'7','moving')
        self.assertEqual(result['distance_miles'],2)
        self.assertEqual(result['seconds'],1000);self.assertEqual(result['time_basis'],'moving')
        self.assertEqual(local_date(activity),'2026-10-09')
        self.assertEqual(metrics(activity,'7','elapsed')['seconds'],1300)
        activity['moving_time']=0
        self.assertEqual(metrics(activity,'7','moving')['time_basis'],'elapsed')
        self.assertFalse(needs_gps({'has_route':True}));self.assertFalse(needs_gps({'route_opt_out':True,'has_route':False}))

if __name__=='__main__':unittest.main()

class ChallengeFlowTests(unittest.TestCase):
    def test_preview_defaults_and_live_export_use_existing_provider_and_local_run_date(self):
        from unittest.mock import patch, MagicMock
        from export_challenge import run_export
        import os
        activity={'id':42,'type':'Run','start_date_local':'2026-10-02T08:00:00','distance':3218.688,'moving_time':1000,'elapsed_time':1300,'visibility':'everyone','private':False}
        setup={'athlete_id':'7','start_date':'2026-09-20','targets':[{'date':'2026-10-02','status':'pending','has_route':False,'activity_id':None}]}
        provider=MagicMock()
        provider.get.side_effect=lambda path,params=None: {'id':7} if path=='athlete' else ({'latlng':{'data':[[38.9,-77],[38.91,-77.01]]}} if path.endswith('/streams') else activity)
        for preview in [None,'false']:
            env={'CHALLENGE_SYNC_URL':'https://example.invalid/api/strava-sync','CHALLENGE_SYNC_SECRET':'a'*48}
            if preview is not None:env['CHALLENGE_SYNC_PREVIEW']=preview
            with patch.dict(os.environ,env,clear=True),patch('export_challenge.load_config',return_value={'source':'strava'}),patch('export_challenge.load_activities',return_value={'42':activity}),patch('export_challenge.Provider',return_value=provider),patch('export_challenge.site_request',side_effect=[setup,{'results':[{'outcome':'completed','route_added':True}]}]) as request:
                counts=run_export();self.assertEqual(counts['completed'],1)
                body=request.call_args.kwargs['json'];self.assertEqual(body['dry_run'],preview is None);self.assertEqual(body['activities'][0]['points'][0],[-77.0,38.9]);self.assertEqual(body['activities'][0]['date'],'2026-10-02')

    def test_private_activities_are_skipped_by_default(self):
        from unittest.mock import patch, MagicMock
        from export_challenge import run_export
        import os
        activity={'id':42,'type':'Run','start_date_local':'2026-10-02T08:00:00','distance':3218.688,'moving_time':1000,'visibility':'followers_only'}
        setup={'athlete_id':'7','start_date':'2026-09-20','targets':[{'date':'2026-10-02','status':'pending','has_route':False,'activity_id':None}]}
        provider=MagicMock();provider.get.side_effect=lambda path,params=None: {'id':7} if path=='athlete' else activity
        with patch.dict(os.environ,{'CHALLENGE_SYNC_URL':'https://example.invalid/api/strava-sync','CHALLENGE_SYNC_SECRET':'a'*48},clear=True),patch('export_challenge.load_config',return_value={'source':'strava'}),patch('export_challenge.load_activities',return_value={'42':activity}),patch('export_challenge.Provider',return_value=provider),patch('export_challenge.site_request',return_value=setup) as request:
            counts=run_export();self.assertEqual(counts['private_activity_skipped'],1);self.assertEqual(request.call_count,1)
