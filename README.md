# Telegram Trade Recording Bot

라오어 무한매수법용 구글 스프레드시트 자동기입 봇입니다.  
기본 템플릿 파일은 `/Users/test/AIassistant/spreadsheet_template.xlsx` 입니다.

이 프로그램은 텔레그램 메시지를 입력으로 받아 체결 정보를 시트에 기록하고, 결과를 텔레그램으로 회신합니다.

초기 스프레드시트 준비(먼저 수행):
- 기본 템플릿(`spreadsheet_template.xlsx`)을 Google 스프레드시트로 업로드
- 셀 `B1`에 종목명 입력
- 셀 `B4`에 원금 입력
- 위 3단계를 완료하면 해당 시트는 기록 대상 시트로 준비 완료

## 1) 주요 기능

- 메리츠 체결 안내 메시지 파싱 후 시트 자동 기입
- 업비트 명령 기반 체결 조회 후 시트 자동 기입
- 기입 전 스프레드시트 XLSX 백업
- 전략(Strategy) 구조로 메시지 처리 루틴 분리

## 2) 사전 준비

1. Python 가상환경
```bash
cd /Users/test/AIassistant
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Google 서비스 계정
- `service_account.json` 준비
- `.env`의 `GOOGLE_SERVICE_ACCOUNT_FILE` 설정
- 대상 스프레드시트를 서비스계정 `client_email`에 `편집자` 권한으로 공유

3. 업비트 API (업비트 루틴 사용 시)
- Access Key / Secret Key 발급
- 허용 IP 등록

4. 텔레그램 봇 (필수)
- Telegram에서 `@BotFather` 실행
- `/newbot`으로 봇 생성 후 토큰 발급
- 발급 토큰을 `.env`의 `TELEGRAM_BOT_TOKEN`에 설정
- 봇과 대화방(개인/그룹)을 만든 뒤 테스트 메시지 1회 전송

### service_account.json 준비 방법

1. Google Cloud Console에서 프로젝트 생성 또는 선택
2. `APIs & Services > Library`에서 아래 API 활성화
- Google Sheets API
- Google Drive API
3. `APIs & Services > Credentials > Create Credentials > Service account` 생성
4. 생성된 서비스 계정에서 `Keys > Add key > Create new key > JSON` 선택
5. 다운로드된 JSON 파일을 `/Users/test/AIassistant/service_account.json`으로 저장
6. `.env`에 경로 설정
```env
GOOGLE_SERVICE_ACCOUNT_FILE=/Users/test/AIassistant/service_account.json
```
7. 해당 JSON의 `client_email`을 복사해 대상 스프레드시트에 편집자 권한으로 공유

## 3) 환경변수

필수:
- `GOOGLE_SERVICE_ACCOUNT_FILE`
- `TELEGRAM_BOT_TOKEN`
- `SPREADSHEET_ID_MAP` 또는 `SPREADSHEET_ID_MAP_FILE`

예시:
```env
GOOGLE_SERVICE_ACCOUNT_FILE=/Users/test/AIassistant/service_account.json
TELEGRAM_BOT_TOKEN=...

SPREADSHEET_ID_MAP_FILE=/Users/test/AIassistant/spreadsheet_map.json
WORKSHEET_NAME=
TIMEZONE=Asia/Seoul
STATE_FILE=/Users/test/AIassistant/state.json
START_FROM_LATEST_ON_FIRST_RUN=true
TELEGRAM_POLL_TIMEOUT=30
TELEGRAM_POLL_INTERVAL=2
SPREADSHEET_BACKUP_DIR=/Users/test/AIassistant/spreadsheet_backups

UPBIT_ENABLED=true
UPBIT_ACCESS_KEY=...
UPBIT_SECRET_KEY=...
UPBIT_BASE_URL=https://api.upbit.com
UPBIT_ORDERS_PATH=/v1/orders
UPBIT_MARKET_SHEET_MAP=KRW-SYMBOL_A:SYMBOL_A,KRW-SYMBOL_B:SYMBOL_B
UPBIT_COMMAND_PREFIX=업비트
```

참고:
- `SPREADSHEET_ID_MAP_FILE`을 사용하면 파일 매핑이 적용됩니다.
- 예시는 `/Users/test/AIassistant/spreadsheet_map.json.example` 참고.

## 4) 스프레드시트 매핑 형식

### A. 문자열 매핑 (`SPREADSHEET_ID_MAP`)
```env
SPREADSHEET_ID_MAP=SYMBOL_A:sheet_id_a,SYMBOL_B:sheet_id_b
```

### B. JSON 파일 매핑 (`SPREADSHEET_ID_MAP_FILE`)
```json
{
  "SYMBOL_A": "sheet_id_a",
  "SYMBOL_B": "sheet_id_b"
}
```

Google 시트 ID는 URL의 `/d/`와 `/edit` 사이 문자열입니다.

## 5) 실행

```bash
cd /Users/test/AIassistant
source .venv/bin/activate
python main.py
```

## 6) 텔레그램 입력 형식

업비트 명령:
- `업비트 SYMBOL 기록`
- `업비트 SYMBOL 기록 : YYYY-MM-DD`
- `업비트 SYMBOL 기록 : YY-MM-DD`
- ex) 텔레그램 메시지 명령 : 업비트 BTC 기록

메리츠 체결 메시지:
- `[메리츠증권] 해외주식 주문체결 안내` 원문 템플릿을 그대로 복사하여 텔레그램으로 전송
- `종목명` 괄호 안 심볼을 기준으로 대상 시트를 결정

## 7) 처리 흐름

1. 메시지 수신
2. 업비트 명령 형식인지 검사
3. 아니면 메리츠 체결 안내 형식 검사
4. 대상 시트 확인
5. XLSX 백업 생성
6. 셀 탐색 후 값 기입
7. 텔레그램 결과 회신

## 8) 기록 규칙 요약

메리츠 루틴:
- 체결일자 기준 날짜 행 탐색/생성
- 기준값 비교로 매수 영역 셀 분기 기입

업비트 루틴:
- 명령 심볼에 대응되는 단일 마켓만 조회
- 매수(bid) 체결만 처리
- 거래금액 비율과 기준 셀 값을 비교해 기입 위치 결정

## 9) 응답 형식

기입 성공 시:
```text
구글스프레드시트(시트이름) 기입 완료
현재 평단가 : ...
현재 주가 : ...

오늘 매수 시도액
LOC 평단 : ...
LOC 큰수 : ...

오늘 매도 시도액
매도 지정가 : ...
매도 수량 : ...
```

업비트 명령은 요약이 함께 회신됩니다.

## 10) 백업

- 기입 전에 대상 스프레드시트를 XLSX로 백업
- 기본 경로: `/Users/test/AIassistant/spreadsheet_backups`
- 환경변수: `SPREADSHEET_BACKUP_DIR`

## 11) 확장 구조

코드는 `공통 엔진 + 전략(Strategy)` 구조입니다.

- 공통 엔진: 업데이트 수신, 컨텍스트 생성, 전략 디스패치
- 전략 핸들러: 업비트 명령 처리, 메리츠 메시지 처리

새 루틴 추가:
1. `handle_xxx_strategy(ctx)` 작성
2. 판별/기입/응답 로직 구현
3. `build_strategies()`에 등록

## 12) 트러블슈팅

`401 Unauthorized`:
- 업비트 키/시크릿/허용 IP/권한 확인

`403` Google API:
- Google Sheets API, Google Drive API 활성화
- 서비스계정 공유 권한 확인

기입 0건:
- 명령 날짜/형식 확인
- 매핑(`SPREADSHEET_ID_MAP`, `UPBIT_MARKET_SHEET_MAP`) 확인
- 로그(`upbit_fetch_done`, `upbit_sheet_write`) 확인
