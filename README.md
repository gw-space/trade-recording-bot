# Telegram Trade Recording Bot

라오어 무한매수법용 구글 스프레드시트 자동기입 봇입니다.  
기본 템플릿 파일은 `/Users/test/AIassistant/spreadsheet_template.xlsx` 입니다.

이 프로그램은 텔레그램 메시지를 입력으로 받아 체결 정보를 시트에 기록하고, 결과를 텔레그램으로 회신하며, 오늘 진행해야할 매수금액과 매도금액을 알려줍니다.

초기 스프레드시트 준비(먼저 수행):
- 기본 템플릿(`spreadsheet_template.xlsx`)을 Google 스프레드시트로 업로드
- 셀 `B1`에 종목명 입력
- 셀 `B4`에 원금 입력
- 위 3단계를 완료하면 해당 시트는 기록 대상 시트로 준비 완료

## 1) 주요 기능

- 메리츠 체결 안내 메시지 파싱 후 시트 자동 기입
- 업비트 명령 기반 체결 조회 후 시트 자동 기입
- 매도 완료 메시지 수신 시 별도 결과표 스프레드시트에 자동 기록
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

## 3) 환경변수(.env 파일 설정)

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

RESULT_SPREADSHEET_ID=your_result_spreadsheet_id
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
- ex) 텔레그램 메시지 전송 : "업비트 BTC 기록" 또는 "업비트 BTC 기록 : 2026-02-20"

메리츠 체결 메시지:
- `[메리츠증권] 해외주식 주문체결 안내` 원문 템플릿을 그대로 복사하여 텔레그램으로 전송
- `종목명` 괄호 안 심볼을 기준으로 대상 시트를 결정

매도 완료 명령:
- `SYMBOL 매도 완료`
- ex) `BTC 매도 완료` 또는 `TQQQ 매도 완료`
- 해당 종목 무한매수 시트의 요약 데이터를 읽어 별도 결과표 스프레드시트에 기록

## 7) 처리 흐름

1. 메시지 수신
2. 매도 완료 형식인지 검사 → 결과표 기록
3. 업비트 명령 형식인지 검사
4. 아니면 메리츠 체결 안내 형식 검사
5. 대상 시트 확인
6. XLSX 백업 생성
7. 셀 탐색 후 값 기입
8. 텔레그램 결과 회신

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

## 10) 자동 백업

- 기입 전에 대상 스프레드시트를 XLSX로 백업
- 기본 경로: `/Users/test/AIassistant/spreadsheet_backups`
- 환경변수: `SPREADSHEET_BACKUP_DIR`

## 11) 매도 완료 → 결과표 기록

`SYMBOL 매도 완료` 메시지를 수신하면, 해당 종목의 무한매수 시트에서 요약 데이터를 읽어 별도 결과표 스프레드시트에 자동 기록합니다.

### 사전 설정
1. 결과표 템플릿(`spreadsheet_result_template.xlsx`)을 Google 스프레드시트로 업로드
2. `.env`에 `RESULT_SPREADSHEET_ID` 설정 (결과표 스프레드시트 ID)
3. 결과표 스프레드시트에 서비스 계정을 편집자 권한으로 공유

### 결과표 컬럼 구조
| A | B | C | D | E | F |
|---|---|---|---|---|---|
| 회차 | 기간 | 총매수금액 | 총판매금액 | 수익 | 종목 |

### 데이터 산출 방식
- **총매수금액**: 무한매수 시트 투자금 합계(요약행)
- **총판매금액**: R11(지정가매도) × 총수량(요약행)
- **수익**: 총판매금액 - 총매수금액
- **기간**: 데이터 행의 첫 날짜 ~ 마지막 날짜

### 응답 형식
```text
BTC 매도 완료 → 결과표 기록 완료
회차: 2
기간: 26.02.16~26.03.16
총매수금액: ₩4,873,497.00
총판매금액: ₩5,360,910.00
수익: ₩487,413.00
```
