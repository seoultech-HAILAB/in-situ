# TRACE 개발용 팀 실행

현재는 아이디·비밀번호 없이 사용합니다. 실행과 GitHub 인계 절차는 [README](../README.md), [개발 인계](DEVELOPER_HANDOFF.md)를 따르세요. 과거 ABC·P01~03 배정은 현재 실행 방식이 아닙니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-team.ps1
# 필요할 때만 외부 URL 생성
powershell -ExecutionPolicy Bypass -File scripts/share-team.ps1
# 서버/터널 종료
powershell -ExecutionPolicy Bypass -File scripts/stop-team.ps1
```

팀 서버 주소: http://127.0.0.1:8001/ . 기록은 `.local/pilot/sessions`에 저장됩니다. 계정은 생성하지 않습니다. 외부 URL은 신뢰하는 개발자에게만 전달하세요. 접속자는 개발자 기능을 사용할 수 있습니다.

개발자는 `codex/` 브랜치에서 변경을 push하고 main을 base로 PR을 제출합니다. main 보호 규칙을 변경하지 않습니다. `.env`, `.local`, 개인 계정·로그는 커밋하지 않습니다. 현재 과제는 `tasks/candidates`에 포함되어 새 PC에서 자동 준비됩니다.
