"""Researcher-only explanations of the frozen candidate's initial errors.

These describe stored ground truth, not a diagnosis of the participant's latest code.
Candidate files, code, publication state and evaluation keys are never changed here.
"""
import difflib

from .pipeline import prepare


def _guides(candidate):
    cid = candidate['id']
    mapping = candidate.get('researcher_notes', {}).get('domain_mapping', {})
    key = lambda name: mapping.get(name, name)
    if cid in ('VERIFY2-M1-A', 'VERIFY2-M1-B'):
        return {2: (
            '시간 파서가 AM은 인식하지만 축약 접미사 A를 오전으로 인식하지 않습니다.',
            '1201a가 자정 직후 00:01 대신 정오 직후 12:01이 됩니다. 이후 통합 일시와 시간순 정렬에도 영향이 전파됩니다.',
            '시간 끝의 A/AM과 P/PM을 모두 인식하고, 오전 12시는 0시로 변환합니다. 참조 코드는 A(?:M)? / P(?:M)? 정규식을 사용합니다.')}
    if cid in ('VERIFY2-M2-A', 'VERIFY2-M2-B'):
        return {3: (
            '구역별 최대 매출 후보를 고르기 전에 drop_duplicates(keep="first")로 첫 후보만 남깁니다.',
            '같은 구역의 더 좋은 후보가 미리 삭제됩니다. Z-94016의 예상 매출은 1,841,351 대신 1,866,261, 비용은 1,546,690 대신 1,227,024여야 합니다. 행 수는 같아도 선택된 값이 틀립니다.',
            '중복 제거 전에 구역별 최대 예상 매출을 계산해 해당 후보를 선택합니다. 동률 후보에만 원래 순서의 첫 행 규칙을 적용한 뒤 환율을 연결합니다.')}
    if cid in ('VERIFY2-M3-A', 'VERIFY2-M3-B'):
        return {3: (
            'DatetimeIndex인 월별 표에 PeriodIndex인 반환 집계 Series를 그대로 할당합니다.',
            'pandas가 위치 대신 인덱스 라벨로 정렬하므로 반환 금액·건수·평균 기간이 NaN이 됩니다. 반환 기록이 있는 달도 최종 출력에서 빈 값으로 남습니다.',
            '세 반환 집계를 months.to_period("M") 순서로 reindex한 다음 .to_numpy()로 할당합니다. 또는 양쪽 인덱스 타입과 월 순서를 명시적으로 일치시킵니다. 반환이 없는 달의 빈 값은 유지합니다.')}
    if cid in ('VERIFY3-H1-A', 'VERIFY3-H1-B'):
        status, order, date = key('Delivered'), key('order_id'), key('date_order_placed')
        return {
            2: (
                f'{status} 상태만 남겨 다른 상태의 기록과 날짜를 누락하고, 반복 원본 행을 {order} 단위로 복원하지 않습니다.',
                '후속 조인에 전달할 주문/대여 정보가 불완전해 필요한 결과 행이 사라지고, 중복 입력이 금액 합산에 영향을 줄 수 있습니다.',
                f'상태 필터를 제거하고 Cancelled·{status}·Part Completed의 비어 있지 않은 날짜로 {date}를 복원합니다. 식별자를 숫자로 정제한 뒤 {order}별 한 행을 남깁니다.'),
            3: (
                f'id_part1을 {order} 연결 키로 사용하고 품목을 {status} 상태로만 제한합니다. 실제 연결 키는 id_part3입니다.',
                '다른 주문/대여의 품목이 잘못 연결되거나 필요한 품목이 누락되어 최종 총액과 결과 행이 틀립니다. Step 4의 합산 결과 차이는 이 입력 오류의 영향도 포함합니다.',
                f'{order}를 id_part3에서, 상품/장비 식별자는 id_part2에서 가져옵니다. 품목 상태 제한은 제거합니다. Step 2와 Step 3을 모두 고쳐야 전체 Target과 일치합니다.')}
    if cid in ('VERIFY3-H2-A', 'VERIFY3-H2-B'):
        code, value, warehouse = key('Code'), key('value'), key('Warehouse')
        contents, location = key('Contents'), key('Location')
        return {
            1: (
                f'{warehouse} 연결 키에 식별자 {code} 대신 수용량 Capacity의 {value} 값을 넣습니다.',
                '용량과 우연히 같은 식별자를 가진 보관소로 연결되어 지역과 보관 품목의 관계가 잘못됩니다. Step 2는 잘못된 키를 전달받는 단계입니다.',
                f'{warehouse}를 pd.to_numeric(warehouse_info["{code}"], errors="coerce")로 만듭니다. Capacity 값은 보관소 식별자로 사용하지 않습니다.'),
            3: (
                '두 지역 모두에 있는 품목의 교집합 대신 두 지역 중 어느 곳에든 있는 품목의 합집합을 반환합니다.',
                '한 지역에만 있는 품목도 출력됩니다. 초기 3행 대신 올바른 결과는 2행입니다. 키 오류만 수정해도 이 조건 오류는 남습니다.',
                f'{contents}별 {location} 고유 개수를 집계해 두 지역 모두에 있는 값(개수 2)만 출력합니다. Step 1과 Step 3을 모두 수정해야 합니다.')}
    return {}


def diagnostics(candidate):
    notes = candidate.get('researcher_notes', {})
    faults = notes.get('fault_steps')
    known = (isinstance(faults, list)
             and all(type(n) is int and 1 <= n <= len(candidate['steps']) for n in faults)
             and len(set(faults)) == len(faults))
    result = {'status': 'error' if known and faults else 'normal' if known else 'unknown',
              'fault_steps': sorted(faults) if known else [], 'errors': [],
              'propagated_steps': [], 'evidence': []}
    if not known:
        result['note'] = notes.get('error_explanation') or '초기 오류 위치가 아직 등록되지 않았습니다. 오류 없음으로 판정한 과제가 아닙니다.'
        return result
    guides = _guides(candidate)
    initial = prepare(candidate['initial_code'], candidate['steps'], engine='python')
    reference = None
    if candidate.get('reference_code'):
        try:
            reference = prepare(candidate['reference_code'], candidate.get('reference_steps', candidate['steps']), engine='python')
        except (ValueError, SyntaxError):
            pass
    defects = {item.get('step'): item.get('description', '') for item in notes.get('defects', []) if isinstance(item, dict)}
    for number in sorted(faults):
        step = initial['steps'][number-1]
        problem, impact, repair = guides.get(number, (
            defects.get(number) or notes.get('error_explanation') or '이 Step에 오류가 등록되어 있습니다.',
            '구체적인 영향 해설은 아직 등록되지 않았습니다.', '연구자 참조 코드와 Target을 확인하세요.'))
        item = {'step': number, 'label': step['intent_label'], 'code_location': step['code_location'],
                'problem': problem, 'impact': impact, 'repair': repair}
        if reference and len(reference['steps']) == len(initial['steps']):
            item['code_diff'] = '\n'.join(difflib.unified_diff(
                step['code'].splitlines(), reference['steps'][number-1]['code'].splitlines(),
                fromfile=f'초기 Step {number}', tofile=f'참조 Step {number}', lineterm=''))
        result['errors'].append(item)
    result['propagated_steps'] = [item['step'] for item in notes.get('trace_summary', [])
                                  if item.get('matches_reference') is False and item.get('step') not in faults]
    checks = notes.get('app_runtime_results', {})
    initial_check, reference_check = checks.get('initial'), checks.get('reference')
    runtime = notes.get('runtime_checks', [])
    if not initial_check:
        initial_check = next((item for item in runtime if item.get('variant') == 'initial'), None)
    if not reference_check:
        reference_check = next((item for item in runtime if item.get('variant') == 'both'), None)
    for label, check in [('저장된 초기 실행', initial_check), ('저장된 참조 실행' if not faults else '저장된 전체 수정 실행', reference_check)]:
        if check and type(check.get('target_match')) is bool:
            result['evidence'].append(f'{label}: Target {"일치" if check["target_match"] else "불일치"}')
    if len(faults) > 1:
        partial = [item for item in runtime if len(item.get('repaired_steps', [])) == 1]
        if len(partial) == len(faults) and all(item.get('target_match') is False for item in partial):
            result['evidence'].append('각 오류 Step을 하나씩만 수정한 실행은 모두 Target 불일치')
    result['note'] = ('정상 대조 과제입니다. 등록된 초기 코드에 오류가 없으며 불필요한 수정은 하지 않습니다.' if not faults
                      else '오류 개수는 잘못된 의미 Step 수입니다. 한 Step 안에 여러 잘못된 처리가 포함될 수 있습니다.')
    return result
