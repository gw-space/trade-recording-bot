# Telegram + Upbit + Google Sheets Auto Fill

이 프로그램은 텔레그램 메시지를 입력 채널로 사용해, 체결 내역을 Google 스프레드시트에 자동 기록하고 결과를 다시 텔레그램으로 회신합니다.

- 메리츠 체결 안내 메시지 파싱 -> TQQQ 시트 기록
- 텔레그램 명령 실행 -> 업비트 BTC 체결 조회/기록

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
- `.env`의 `GOOGLE_SERVICE_ACCOUNT_FILE` 설정

3. Google 스프레드시트 공유
- `service_account.json`의 `client_email`을 대상 스프레드시트에 `편집자`로 공유
- TQQQ 시트, 비트코인 시트 모두 공유

4. 업비트 API 키
- 업비트 Open API에서 Access/Secret 발급
- 허용 IP 등록

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
SPREADSHEET_BACKUP_DIR=/Users/test/AIassistant/spreadsheet_backups

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

## 4) 텔레그램 동작 방식

프로그램은 텔레그램 `getUpdates` 롱폴링으로 새 메시지를 기다립니다. 메시지가 들어오면 아래 순서로 처리합니다.

1. 입력 메시지 확인
- 업비트 명령인지 검사
- 아니면 메리츠 체결 안내 형식인지 검사

2. 업비트 명령이면
- 업비트에서 지정 날짜 체결 조회
- BTC + 매수(bid)만 대상으로 필터링
- 시트 기입 전에 XLSX 백업 생성
- 규칙에 맞게 LOC평단/LOC고가/수량 기입
- 결과 텔레그램 회신

3. 메리츠 체결 메시지면
- 메시지에서 종목/체결일자/체결단가/체결수량 파싱
- 시트 기입 전에 XLSX 백업 생성
- 날짜행 탐색/생성 후 LOC평단 또는 LOC고가 기입
- 결과 텔레그램 회신

## 5) 텔레그램 입력 형식

업비트 명령:
- `업비트 기록 수행`
- `업비트 기록 수행 : YYYY-MM-DD`
- `업비트 기록 수행 : YY-MM-DD` (예: `26-02-20`)

메리츠 체결 메시지:
- `[메리츠증권] 해외주식 주문체결 안내` 템플릿 메시지를 그대로 전송

## 6) 텔레그램 응답 형식

기록 성공 시 같은 채팅방으로 아래 형태로 회신합니다.

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

업비트 명령 응답은 상단에 요약이 추가됩니다.

```text
업비트 기록 수행 완료
- 처리 체결 수: N
- 시트 기입 수: M

(위 기입 완료 메시지)
```

## 7) 기록 수행 전 스프레드시트 백업

- 실제 셀 기입 전에 대상 스프레드시트를 XLSX로 로컬 백업
- 기본 폴더: `/Users/test/AIassistant/spreadsheet_backups`
- 종목별 하위 폴더:
  - `spreadsheet_backups/BTC`
  - `spreadsheet_backups/TQQQ`
- 환경변수: `SPREADSHEET_BACKUP_DIR`

## 8) 기록 규칙

메리츠(TQQQ):
- 기존 규칙대로 날짜/LOC평단/LOC고가/수량 기입

업비트(BTC):
- BTC + 매수(bid)만 처리
- 기준 셀: `B3(0.5회당)`, `R6(평단가)`
- `거래금액 ~= B3*2` (0.8~1.2):
  - LOC평단/LOC고가 둘 다 기입
  - 수량은 `거래수량/2`씩 기입
- `거래금액 ~= B3` (0.8~1.2):
  - `거래단가 > R6` 이면 LOC고가
  - 그 외 LOC평단
- 조건 불일치면 기입하지 않음

## 9) 응답 통화 규칙

- TQQQ 응답: 달러(`$`)
- BTC 응답: 원화(`₩`)

대상 필드:
- 현재 평단가
- 현재 주가
- LOC 평단
- LOC 큰수
- 매도 지정가

## 10) 로그

표준 출력 로그 예시:
- `bot_start`
- `updates_received`
- `update_processing`
- `upbit_fetch_done`
- `upbit_ratio_check`
- `upbit_sheet_write`
- `spreadsheet_backup_done`
- `telegram_reply_sent`
- `processed update_id=...`

## 11) 트러블슈팅

1. `401 Unauthorized` (업비트)
- API 키/시크릿 확인
- 허용 IP 등록 확인
- 키 권한(주문 조회) 확인

2. `403` (Google API)
- Google Sheets API 활성화
- Google Drive API 활성화 (XLSX export 백업에 필요)
- 서비스 계정 이메일 공유(편집자) 확인

3. `fills=0`
- 날짜 명령 확인
- `UPBIT_ORDERS_PATH=/v1/orders` 확인
- 로그의 `upbit_fetch_done` 값 확인
