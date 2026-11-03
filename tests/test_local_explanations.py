"""Regression coverage for operation-local prose and retired source-path caches."""
import ast
import copy
import json
import pytest

from backend.transformations import extract, annotate_run, VERSION
from backend.transformation_selection import selected_transformation, validate_selected_edit
from backend.pipeline import prepare, assemble
from backend.python_runtime import run as native_run
from backend.engine import parse_table
from backend import explanations

CITY_CODE = """stores = input_df.copy()
location_parts = stores['Location'].str.split(',', n=1, expand=True)
stores['City'] = location_parts[0].str.strip()
stores['Country'] = location_parts[1].str.strip()
result = stores
"""


def city(code=CITY_CODE, indices=None):
    return next(t for t in extract(code, indices or list(range(len(ast.parse(code).body))))
                if t['output_columns'] == ['City'] and t['method'] == 'strip')


def snapshot():
    plan = prepare(CITY_CODE, [{'statement_indices': list(range(5)), 'output_variable': 'result'}], engine='python')
    stages, ops = assemble(native_run(CITY_CODE, parse_table('Location\n" Seoul , Korea "'), {}, plan), plan)
    return annotate_run({'id': 'current-run', 'code_version': 1, 'code': CITY_CODE,
                         'pipeline': plan, 'stages': stages, 'operations': ops})


def test_city_keeps_current_code_position_and_local_description_without_backtracking():
    item = city()
    assert item['code'] == 'location_parts[0].str.strip()'
    assert item['code_location']['start'] == 3 and item['output_columns'] == ['City']
    assert 'source_context' not in item
    assert '공백' in item['description']['text']
    assert 'Location' not in item['description']['text'] and '분할' not in item['description']['text']
    assert city(indices=[2])['description'] == item['description']
    # A different earlier definition does not replace this operation's prose.
    changed = city(CITY_CODE.replace("split(',',", "split(';',"))
    assert changed['description'] == item['description'] and changed['id'] == item['id']


def test_helpers_keep_their_local_code_location_without_upstream_definitions():
    code = "def clean(parts):\n    return parts[0].str.strip()\nlocation_parts = input_df['Location'].str.split(',', expand=True)\nresult = input_df.assign(City=clean(location_parts))"
    item = city(code)
    assert item['code_location']['start'] == 2
    assert 'source_context' not in item
    assert 'Location' not in item['description']['text']


def test_old_in_session_explanations_and_ready_flags_are_invalidated():
    run = snapshot()
    table = copy.deepcopy(run['stages'][1]['table'])
    run.update(transformations_version='ast-transformations-v1', explanation_status='ready',
               explanation_meta={'prompt_version': 'executed-code-korean-prose-v3'})
    stage = run['stages'][1]
    stage['nl_explanation'] = {'title': 'old', 'text': 'old source path'}
    stage['column_explanations'] = {'City': 'old source path'}
    for item in stage['transformations']:
        item['description'] = {'text': 'old source path', 'source': 'llm'}
        item['source_context'] = {'definitions': ['old variable definition']}
    run['pipeline']['steps'][0]['transformations'][0]['source_context'] = {'definitions': ['old variable definition']}
    annotate_run(run)
    assert run['transformations_version'] == VERSION
    assert 'explanation_status' not in run and 'explanation_meta' not in run
    assert 'nl_explanation' not in stage and 'column_explanations' not in stage
    assert all('source_context' not in item and item['description']['source'] == 'ast' for item in stage['transformations'])
    assert 'source_context' not in json.dumps(run['pipeline'])
    assert run['code'] == CITY_CODE and stage['table'] == table and run['id'] == 'current-run'


def test_new_llm_prose_survives_read_annotation_but_not_code_changes():
    run = snapshot()
    item = next(t for t in run['stages'][1]['transformations'] if t['output_columns'] == ['City'])
    item['description'] = {'text': '앞뒤 공백을 제거합니다.', 'source': 'llm'}
    annotate_run(run)
    current = next(t for t in run['stages'][1]['transformations'] if t['id'] == item['id'])
    assert current['description'] == item['description']
    run['code'] += '\n# edited code'
    annotate_run(run)
    assert all(t['description']['source'] == 'ast' for t in run['stages'][1]['transformations'])


def test_payload_and_prompt_no_longer_require_original_column_paths():
    payload = explanations.model_context(snapshot())
    item = next(t for t in payload['transformation_targets'] if t['output_columns'] == ['City'])
    assert item['code'] == 'location_parts[0].str.strip()'
    assert 'source_context' not in json.dumps(payload)
    assert ' Seoul ' not in json.dumps(payload)
    assert 'source_context' not in explanations.INSTRUCTIONS
    assert '원본 열부터' not in explanations.INSTRUCTIONS
    assert '개별 연산만 설명' in explanations.INSTRUCTIONS


def test_previous_file_cache_is_preserved_but_cannot_be_reused(tmp_path, monkeypatch):
    run = snapshot()
    monkeypatch.setenv('TRACE_EXPLANATION_DIR', str(tmp_path))
    with monkeypatch.context() as previous:
        previous.setattr(explanations, 'PROMPT_VERSION', 'executed-code-korean-prose-v3')
        old_key = explanations.fingerprint(run)
    old_file = tmp_path / (old_key + '.json')
    old_file.write_text(json.dumps({'fingerprint': old_key, 'text': 'old source path'}), encoding='utf-8')
    calls = []

    def generate(current):
        calls.append(current['id'])
        return {'fingerprint': explanations.fingerprint(current), 'prompt_version': explanations.PROMPT_VERSION,
                'steps': [], 'columns': [], 'transformations': []}

    monkeypatch.setattr(explanations, 'generate', generate)
    bundle, cached = explanations.obtain(run)
    assert not cached and calls == [run['id']]
    assert bundle['fingerprint'] != old_key and old_file.exists()
    assert 'old source path' not in json.dumps(bundle)


def test_selected_edit_still_limits_changes_to_current_operation():
    run = snapshot()
    item = city()
    selection = selected_transformation(run, {'step_id': run['stages'][1]['id'], 'transformation_id': item['id'], 'execution_version': run['id']})
    assert selection['code'] == item['code'] and 'source_context' not in selection
    validate_selected_edit(CITY_CODE.replace('location_parts[0].str.strip()', 'location_parts[0].str.strip().str.title()'), run, selection, 'step')
    with pytest.raises(ValueError, match='현재 선택한 연산 밖'):
        validate_selected_edit(CITY_CODE.replace("split(',',", "split(';',"), run, selection, 'step')
    with pytest.raises(ValueError, match='현재 선택한 연산 밖'):
        validate_selected_edit(CITY_CODE.replace('location_parts[1].str.strip()', 'location_parts[1].str.strip().str.upper()'), run, selection, 'step')
