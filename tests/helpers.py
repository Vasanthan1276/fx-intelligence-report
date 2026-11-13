from datetime import datetime, timezone
import numpy as np
import pandas as pd

class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value=cls(2026,11,13,9,0,tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


def model_inputs():
    dates=pd.bdate_range(end='2026-11-12',periods=1700)
    rng=np.random.default_rng(42)
    series=pd.Series(1.3*np.exp(np.cumsum(rng.normal(-0.00004,0.003,len(dates)))),index=dates)
    policy_dates=pd.date_range('2020-01-01',periods=82,freq='MS')
    policies={c:pd.Series(np.linspace(4,2.5,len(policy_dates)),index=policy_dates) for c in ['USD','JPY','EUR','GBP','AUD','MYR','CHF']}
    macro={c:{'growth_current_year':2026,'growth_next_year':2027,'growth_current_pct':2.5,'growth_next_pct':2.8,'inflation_current_year':2026,'inflation_next_year':2027,'inflation_current_pct':2.1,'inflation_next_pct':1.8} for c in [*policies,'SGD']}
    macro['SGD']['growth_next_pct']=3
    return series,policies,macro
