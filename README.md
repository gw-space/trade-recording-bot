# Telegram + Upbit + Google Sheets Auto Fill

이 프로그램은 아래 2가지 작업을 자동화합니다.

- 메리츠 체결 텍스트(텔레그램 수신)를 파싱해 TQQQ 시트에 기록
- 텔레그램 명령으로 업비트 BTC 체결을 조회해 비트코인 시트에 기록

기입 완료 후 같은 텔레그램 채팅방으로 결과 메시지를 회신합니다.

## 1) 사전 준비

1. Python 가상환경
```bash
cd /Users/test/AIassistant
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Google 서비스 계정 키
- `service_account.json` 파일 준비
- `.env`의 `GOOGLE_SERVICE_ACCOUNT_FILE` 경로 설정

3. Google 스프레드시트 공유
- `service_account.json`의 `client_email`을 스프레드시트에 `편집자`로 공유
- TQQQ 시트, 비트코인 시트 둘 다 공유 필요

4. 업비트 API 키
- 업비트 Open API에서 Access/Secret 발급
- 허용 IP 등록 필요

## 2) 환경변수(.env)

최소 필수:
- `GOOGLE_SERVICE_ACCOUNT_FILE`
- `TELEGRAM_BOT_TOKEN`
- `SPREADSHEET_ID_MAP`

예시:
```env
GOOGLE_SERVICE_ACCOUNT_FILE=/Users/test/AIassistant/service_account.json
TELEGRAM_BOT_TOKEN=...
SPREADSHEET_ID_MAP=TQQQ:<tqqq_sheet_id>,BTC:<btc_sheet_id>
WORKSHEET_NAME=
TIMEZONE=Asia/Seoul
STATE_FILE=/Users/test/AIassistant/state.json
START_FROM_LATEST_ON_FIRST_RUN=true
TELEGRAM_POLL_TIMEOUT=30
TELEGRAM_POLL_INTERVAL=2

UPBIT_ENABLED=true
UPBIT_ACCESS_KEY=...
UPBIT_SECRET_KEY=...
UPBIT_BASE_URL=https://api.upbit.com
UPBIT_ORDERS_PATH=/v1/orders
UPBIT_MARKET=KRW-BTC
UPBIT_MARKET_ASSET=BTC
UPBIT_SHEET_SYMBOL=BTC
UPBIT_COMMAND_TEXT=업비트 기록 수행
```

## 3) 실행

```bash
cd /Users/test/AIassistant
source .venv/bin/activate
python main.py
```

## 4) 텔레그램 명령

업비트 기록 명령:
- `업비트 기록 수행`
- `업비트 기록 수행 : YYYY-MM-DD`
- `업비트 기록 수행 : YY-MM-DD` (예: `26-02-20`)

명령 채팅방으로 결과를 회신합니다.

## 5) 기록 수행 전 스프레드시트 백업

- 실제 셀 기입 전에 대상 스프레드시트를 로컬 백업 폴더에 XLSX 파일로 백업
- 기본 폴더: `/Users/test/AIassistant/spreadsheet_backups`
- 환경변수: `SPREADSHEET_BACKUP_DIR`
- 종목별 하위 폴더로 저장: `spreadsheet_backups/BTC`, `spreadsheet_backups/TQQQ`

## 6) 기록 규칙

메리츠(TQQQ):
- 기존 규칙대로 날짜/LOC평단/LOC고가/수량 기입

업비트(BTC):
- BTC + 매수(bid)만 처리
- 기준 셀: `B3(0.5회당)`, `R6(평단가)`
- `거래금액 ~= B3*2` (0.8~1.2):
  - LOC평단/LOC고가 둘 다 기입
  - 수량은 `거래수량/2`씩 기입
- `거래금액 ~= B3` (0.8~1.2):
  - `거래단가 > R6` 이면 LOC고가에 기입
  - 그 외 LOC평단에 기입
- 조건 불일치면 날짜/LOC 모두 기입하지 않음

## 7) 응답 메시지 통화

- TQQQ 응답: 달러(`$`)
- BTC 응답: 원화(`₩`)

대상 필드:
- 현재 평단가
- 현재 주가
- LOC 평단
- LOC 큰수
- 매도 지정가

## 8) 로그

표준 출력 로그 예시:
- `bot_start`
- `poll_wait`
- `updates_received`
- `upbit_fetch_done`
- `upbit_ratio_check`
- `upbit_sheet_write`
- `processed update_id=...`

백업은 Google Drive export API를 사용하므로 Drive API 권한/활성화가 필요할 수 있습니다.

## 9) 트러블슈팅

1. `401 Unauthorized` (업비트)
- API 키/시크릿 확인
- 허용 IP 등록 확인
- 키 권한(주문 조회) 확인

2. `403` (Google API)
- Google Sheets API 활성화
- 서비스 계정 이메일 공유(편집자) 확인

3. `fills=0`
- 날짜 명령 확인
- `UPBIT_ORDERS_PATH=/v1/orders` 확인
- 로그의 `upbit_fetch_done` 값 확인
