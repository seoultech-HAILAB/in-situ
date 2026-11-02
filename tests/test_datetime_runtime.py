import pytest

from backend.engine import parse_table
from backend.pipeline import prepare
from backend.isolation import isolated_run
from backend.python_runtime import validate
from backend.legacy_engine import Unsupported


@pytest.mark.parametrize('code,expected',[
    ("dates = pd.to_datetime(input_df['date'], errors='coerce').dropna()\nresult = pd.DataFrame({'date': [dates.min().strftime('%Y-%m-%d')]})",'2020-01-03'),
    ("from datetime import datetime\nresult = input_df.assign(date=input_df['date'].map(lambda s: datetime.strptime(s, '%Y-%m-%d').strftime('%d/%m/%Y')))",'04/02/2021'),
])
def test_native_datetime_format_and_parse_internal_imports(code,expected):
    plan=prepare(code,engine='python')
    records=isolated_run(code,'date\n2021-02-04\n2020-01-03',engine='python',plan=plan)
    assert records[-1]['table']['rows'][0]['values']['date']==expected


def test_internal_dependency_fix_does_not_enable_explicit_time_import():
    with pytest.raises(Unsupported):
        validate('import time\nresult = input_df.copy()')
