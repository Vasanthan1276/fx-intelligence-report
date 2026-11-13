import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile
from dataclasses import asdict

import pandas as pd
import requests
import main
import reliability as r
import run_update
from validation_audit import build_audit
from helpers import FixedDateTime, model_inputs


def frame():
    dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=400)
    return pd.DataFrame({"USD": 1.1, "JPY": 170., "GBP": .85, "AUD": 1.6,
                         "MYR": 4.5, "CHF": .94, "SGD": 1.42}, index=dates)


def api_response(df):
    rows = df.rename_axis('TIME_PERIOD').reset_index().melt(id_vars='TIME_PERIOD', var_name='CURRENCY', value_name='OBS_VALUE')
    return Mock(text=rows.to_csv(index=False))


def zip_response(df):
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w') as z:
        z.writestr('eurofxref-hist.csv', df.rename_axis('Date').to_csv())
    return Mock(content=content.getvalue())


def http_error(code):
    response = requests.Response()
    response.status_code = code
    return requests.HTTPError(response=response)


class TransportTests(unittest.TestCase):
    def test_primary_normal(self):
        diag = {}
        df, source = r.fetch_history(7, Mock(return_value=api_response(frame())), diag)
        self.assertEqual(source, 'ECB Data Portal API')
        self.assertEqual(len(df), 400)
        self.assertEqual(diag['sources'][0]['status'], 'available')

    @patch('reliability.time.sleep')
    def test_transient_504_recovers(self, sleep):
        get = Mock(side_effect=[http_error(504), api_response(frame())])
        diag = {}
        r.fetch_history(7, get, diag)
        self.assertEqual(len(diag['sources'][0]['attempts']), 2)
        self.assertEqual(diag['sources'][0]['attempts'][0]['error'], 'HTTP 504')

    @patch('reliability.time.sleep')
    def test_timeout_uses_valid_zip(self, sleep):
        get = Mock(side_effect=[requests.Timeout()] * 3 + [zip_response(frame())])
        diag = {}
        _, source = r.fetch_history(7, get, diag)
        self.assertIn('ZIP fallback', source)
        self.assertEqual(diag['sources'][0]['status'], 'failed')

    def test_404_does_not_retry(self):
        get = Mock(side_effect=[http_error(404), zip_response(frame())])
        r.fetch_history(7, get, {})
        self.assertEqual(get.call_count, 2)

    @patch('reliability.time.sleep')
    def test_empty_fallback_fails_visibly(self, sleep):
        old = frame(); old.index = old.index - pd.DateOffset(years=20)
        diag = {}
        with self.assertRaises(RuntimeError):
            r.fetch_history(7, Mock(side_effect=[http_error(504)]*3+[zip_response(old)]), diag)
        self.assertIn('no observations', diag['sources'][1]['error'])

    def test_malformed_payload_falls_back(self):
        get = Mock(side_effect=[Mock(text='<html>Unavailable</html>'), zip_response(frame())])
        self.assertIn('fallback', r.fetch_history(7, get, {})[1])

    def test_empty_dataframe_rejected(self):
        with self.assertRaisesRegex(ValueError, 'no observations'):
            r.validate_history(frame().iloc[:0])

    def test_missing_latest_currency_rejected(self):
        df = frame(); df.loc[df.index[-1], 'JPY'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'missing or implausible'):
            r.validate_history(df)

    def test_short_history_rejected(self):
        with self.assertRaisesRegex(ValueError, 'insufficient'):
            r.validate_history(frame().tail(20))

    def test_stale_history_rejected(self):
        df = frame(); df.index = df.index-pd.Timedelta(days=25)
        with self.assertRaisesRegex(ValueError, 'stale'):
            r.validate_history(df)

    def test_future_history_rejected(self):
        df = frame(); df.index = df.index+pd.Timedelta(days=25)
        with self.assertRaisesRegex(ValueError, 'future'):
            r.validate_history(df)

    def test_zero_and_infinite_historical_rates_rejected(self):
        for value in (0, float('inf'), -1):
            df = frame(); df.iloc[0, 0] = value
            with self.assertRaisesRegex(ValueError, 'non-positive or non-finite'):
                r.validate_history(df)


class BaselineTests(unittest.TestCase):
    def test_full_outputs_match_original_code_for_all_seven_currencies(self):
        expected = json.loads((Path(__file__).parent/'fixtures/phase2c_expected.json').read_text())
        series, policies, macro = model_inputs()
        with patch.object(main, 'datetime', FixedDateTime):
            for label, p, m in [('full', policies, macro), ('missing', {}, {}), ('partial', {}, macro)]:
                for code in main.CURRENCY_CONFIG:
                    with self.subTest(coverage=label, code=code):
                        self.assertEqual(asdict(main.analyse_currency(code, series, {}, p, m)), expected[label][code])

    def test_recommendation_boundaries(self):
        cases = [(3.49, 3.99, 'Wait', 0), (3, 4, 'Light Accumulate', 10),
                 (3.5, 2.49, 'Patient Accumulate', 10), (3.5, 2.5, 'Accumulate', 15),
                 (3.5, 4, 'Accumulate Now', 20), (4, 3.49, 'Buy', 25),
                 (4, 3.5, 'Buy Now', 30), (4.5, 3.74, 'Strong Buy', 30),
                 (4.5, 3.75, 'Exceptional Buy', 40), (1.49, 5, 'Avoid', 0)]
        for score, urgency, label, tranche in cases:
            result = main.recommendation_from_score(score, urgency)
            self.assertEqual((result[0], result[2]), (label, tranche))


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_normal(self, shadow=None):
        patches = {
            'fetch_ecb_history': Mock(return_value=(frame(), 'Test ECB fixture')),
            'current_release_already_processed': Mock(return_value=False),
            'fetch_validation_rates': Mock(return_value={}),
            'fetch_bis_policy_series': Mock(return_value=({}, {c: 'Unavailable' for c in main.POLICY_AREA_CODES})),
            'fetch_imf_macro_snapshot': Mock(return_value=({}, {'growth': 'Unavailable', 'inflation': 'Unavailable'})),
            'fetch_news_shadow_snapshot': Mock(return_value=(shadow or {}, 'Test shadow fixture')),
        }
        with patch.multiple(main, **patches):
            return run_update.run_update(main, self.root)

    def test_normal_update_and_degraded_optional_sources(self):
        self.assertEqual(self.run_normal(), 0)
        data = json.loads((self.root/'fx_signals.json').read_text())
        self.assertEqual(len(data['currencies']), 7)
        self.assertTrue(all(c['effective_macro_weight_pct'] == 0 for c in data['currencies']))
        self.assertTrue(data['baseline_frozen'] and data['shadow_mode'])
        self.assertEqual(json.loads((self.root/'run_status.json').read_text())['state'], 'updated')
        self.assertTrue((self.root/'validation_audit.json').exists())

    def test_shadow_has_zero_effect_on_baseline(self):
        self.run_normal()
        before = json.loads((self.root/'fx_signals.json').read_text())['currencies']
        self.run_normal({c: {'score': 5, 'confidence_pct': 100, 'evidence_eligible': True, 'coverage_quality': 'Strong'} for c in main.CURRENCY_CONFIG})
        after = json.loads((self.root/'fx_signals.json').read_text())['currencies']
        for old, new in zip(before, after):
            for key in ('opportunity_score','buy_urgency_score','forward_outlook_score','recommendation','suggested_buy_pct'):
                self.assertEqual(old[key], new[key])

    def test_source_failure_retains_all_snapshots_and_history(self):
        self.run_normal()
        before = {p.name:p.read_bytes() for p in self.root.glob('*.json') if p.name != 'run_status.json'}
        with patch.object(main, 'fetch_ecb_history', side_effect=RuntimeError('both sources failed')):
            self.assertEqual(run_update.run_update(main, self.root), 1)
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.glob('*.json') if p.name != 'run_status.json'})
        self.assertEqual(json.loads((self.root/'run_status.json').read_text())['state'], 'failed')

    def test_late_failure_does_not_publish_partial_snapshot(self):
        self.run_normal()
        before = (self.root/'fx_signals.json').read_bytes()
        with patch.object(main, 'write_performance_report', side_effect=ValueError('late failure')):
            self.assertEqual(self.run_normal(), 1)
        self.assertEqual(before, (self.root/'fx_signals.json').read_bytes())

    def test_corrupt_history_not_silently_reset(self):
        self.run_normal()
        (self.root/'score_log.json').write_text('{broken')
        self.assertEqual(self.run_normal(), 1)
        self.assertEqual((self.root/'score_log.json').read_text(), '{broken')

    def test_noop_keeps_model_timestamp_and_records_check(self):
        self.run_normal()
        before = (self.root/'fx_signals.json').read_bytes()
        with patch.object(main,'fetch_ecb_history',return_value=(frame(),'Test ECB fixture')), patch.object(main,'current_release_already_processed',return_value=True):
            self.assertEqual(run_update.run_update(main,self.root),0)
        self.assertEqual(before, (self.root/'fx_signals.json').read_bytes())
        self.assertEqual(json.loads((self.root/'run_status.json').read_text())['state'],'no_new_market_data')

    def test_recovery_retains_previous_failure_record(self):
        run_update.record_failure(self.root, 'Test failed source')
        self.run_normal()
        status=json.loads((self.root/'run_status.json').read_text())
        self.assertEqual(status['state'],'updated')
        self.assertEqual(status['previous_failure']['error'],'Test failed source')


class AuditTests(unittest.TestCase):
    def test_pending_neutral_and_decisive_denominators(self):
        stats=main._aggregate_performance([{'outcome':'helpful','action_benefit_pct':1},
            {'outcome':'neutral','action_benefit_pct':0},{'outcome':'unhelpful','action_benefit_pct':-1}])
        self.assertEqual(stats['helpful_rate_pct'],50)
        self.assertEqual(stats['matured_signals'],3)

    def test_evidence_false_and_duplicate_shadow_are_excluded_from_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            payloads={'fx_signals':{'model_version':'v','app_release':'a','currencies':[{'code':'USD'}]},
                'fx_history':{'records':[{'date':f'2026-11-{d:02}','USD':1.1} for d in [9,10,11]]},
                'news_shadow_log':{'records':[]}}
            row={'app_release':'a','market_date':'2026-11-09','rates_sgd':{'USD':1.1},'news_scores':{'USD':4},
                 'news_evidence_eligible':{'USD':True},'news_coverage_quality':{'USD':'Adequate'},'news_confidence_pct':{'USD':50}}
            payloads['news_shadow_log']['records']=[row,row,{**row,'news_evidence_eligible':{'USD':False}}]
            for name,data in payloads.items(): (root/(name+'.json')).write_text(json.dumps(data))
            result=build_audit(root)['shadow']['horizons']
            self.assertEqual(result['1']['matured'],1)
            self.assertEqual(result['1']['duplicate'],1)
            self.assertEqual(result['1']['excluded_evidence'],1)
            self.assertEqual(result['5']['pending'],1)


if __name__ == '__main__':
    unittest.main()
