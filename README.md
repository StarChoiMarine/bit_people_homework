# 비트컴퓨터 사내 직원 관리 시스템

비트컴퓨터의 직원과 관리자가 사용하는 소규모 사내 직원 관리 웹 애플리케이션입니다.
직원은 자신의 정보를 확인하고 변경을 요청할 수 있고, 관리자는 직원 계정과 재직 상태,
정보 변경 요청 및 외부 Background Check 업무를 관리할 수 있습니다.

이 프로젝트는 면접 과제로 설명하기 쉽도록 서버 사이드 렌더링과 명시적인 계층형 구조를
사용합니다. 복잡한 프론트엔드 프레임워크 없이 FastAPI가 HTML을 렌더링하며, 중요한
권한 검사는 화면이 아니라 서버에서 수행합니다.

## 주요 기능

### 공통

- 로그인과 로그아웃
- 역할에 따른 로그인 후 화면 분리
- 서버 저장형 세션과 `HttpOnly` 쿠키
- 현재 비밀번호를 확인한 뒤 비밀번호 변경
- 주요 인사 및 민감정보 작업에 대한 감사로그

### 직원 기능

- `/employees/me`에서 자신의 정보만 조회
- 성, 이름, 생년월일에 대한 정보 변경 요청
- 정보 변경 전 현재 비밀번호 재확인
- 변경된 값이 없으면 요청을 생성하지 않음
- 승인 대기 중인 요청이 있으면 중복 요청 차단
- 거절된 최근 요청 안내 확인 및 일회성 닫기
- 관리자 승인 없이 자신의 비밀번호 변경

직원은 URL에 다른 사번을 넣어 다른 직원의 정보를 조회하는 방식을 사용하지 않습니다.
현재 직원은 항상 로그인 세션의 사번으로 결정됩니다.

### 관리자 기능

- 전체 직원 목록과 직원 상세정보 조회
- 새 직원 계정 생성
- 다른 직원의 로그인 아이디, 성, 이름, 생년월일, 역할 및 비밀번호 수정
- 관리자 직접 수정 전 관리자 본인의 비밀번호 재확인
- 직원 정보 변경 요청 승인 또는 거절
- 정보 변경 요청이나 미확인 Background Check 결과가 있는 직원 표시
- 직원 퇴사 처리와 해당 직원의 모든 활성 세션 즉시 무효화
- Background Check 요청, 진행 상태 확인, 결과 열람 및 정보 파기

관리자는 자신을 직접 퇴사 처리할 수 없습니다. 관리자 자신의 개인정보 변경 요청도
직접 승인할 수 없으며 다른 관리자가 검토해야 합니다. 직원 수정 화면에서 사번,
재직 상태, 퇴사 시각은 전용 업무 흐름을 우회하지 못하도록 읽기 전용입니다.

## 기술 스택

| 구분 | 기술 |
|---|---|
| Backend | Python 3.12, FastAPI |
| HTML 렌더링 | Jinja2 서버 사이드 렌더링 |
| UI | Bootstrap 5.3, 소량의 JavaScript |
| ORM | SQLAlchemy 2.x |
| Database | SQLite, WAL 모드, Foreign Key 활성화 |
| 외부 HTTP | HTTPX 비동기 클라이언트 |
| 테스트 | pytest, FastAPI TestClient, Fake Background Check Client |
| 실행/배포 | Uvicorn, Docker, EC2 대상 |

서비스의 기본 색상은 `#0C4E98`입니다.

## 프로젝트 구조

```text
app/
├── clients/       # 외부 Background Check HTTP 클라이언트
├── core/          # DB 연결, 비밀번호, 시드, 스키마 마이그레이션
├── models/        # SQLAlchemy 모델
├── repositories/  # DB 조회와 저장
├── routers/       # FastAPI 엔드포인트와 HTTP 처리
├── services/      # 인증, 직원, 변경 요청, Background Check 업무 규칙
├── static/        # CSS
├── templates/     # Jinja2 HTML
└── main.py        # 애플리케이션 시작점과 백그라운드 폴러 실행
tests/             # 인증, 인가, 트랜잭션, 외부 API 및 마이그레이션 테스트
Dockerfile         # 단일 컨테이너 실행 설정
```

요청은 다음 순서로 처리합니다.

```text
Browser → Router → Service → Repository → SQLAlchemy Model → SQLite
                        ↓
              Background Check Client → External API
```

- Router는 폼 입력과 HTTP 응답을 처리합니다.
- Service는 권한 이후의 업무 규칙과 트랜잭션을 담당합니다.
- Repository는 SQLAlchemy 조회와 저장을 담당합니다.
- Model은 테이블과 Enum을 정의합니다.

## 실행 방법

### 로컬 실행

Python 3.12 이상을 권장합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
mkdir -p .secrets
python -m app.core.generate_seed_credentials \
  --output .secrets/seed_credentials.json
export SEED_CREDENTIALS_FILE=.secrets/seed_credentials.json
uvicorn app.main:app --workers 1 --host 0.0.0.0 --port 8000
```

브라우저에서 `http://localhost:8000`으로 접속합니다. 최초 시작 시 테이블을 생성하고
아래 시드 계정을 자동으로 추가합니다. 이미 같은 사번이 있으면 해당 계정은 다시 만들거나
초기화하지 않습니다.

로컬 SQLite 파일의 기본 위치는 `data/employee_portal.db`입니다.

### Docker 실행

로컬에서 Docker volume을 사용해 실행하는 예시입니다.

```bash
docker build -t bit-people-portal .
docker run --rm \
  -p 8000:8000 \
  -v bit-people-data:/app/data \
  -v "$PWD/.secrets/seed_credentials.json:/run/secrets/seed_credentials.json:ro" \
  -e SEED_CREDENTIALS_FILE=/run/secrets/seed_credentials.json \
  bit-people-portal
```

Docker에서는 `DATABASE_PATH=/app/data/employee_portal.db`를 기본값으로 사용합니다.
DB 파일과 WAL 관련 파일은 `/app/data` volume에 저장되므로 컨테이너를 교체해도 데이터가
유지됩니다. SQLite와 애플리케이션 내부 폴러의 중복 실행을 피하기 위해 Uvicorn worker는
한 개로 실행합니다.

### EC2 배포 예시

운영 환경에서는 DB와 자격증명을 서로 다른 host 경로에 보관하고, 자격증명 파일은 컨테이너에
읽기 전용으로 연결합니다.

```bash
docker run -d \
  --name employee-portal \
  --restart unless-stopped \
  -p 8080:8000 \
  -v /opt/employee-portal/data:/app/data \
  -v /opt/employee-portal/secrets/seed_credentials.json:/run/secrets/seed_credentials.json:ro \
  -e DATABASE_PATH=/app/data/employee_portal.db \
  -e SEED_CREDENTIALS_FILE=/run/secrets/seed_credentials.json \
  employee-portal
```

`/opt/employee-portal/data`에는 SQLite DB를 보관하고, `/opt/employee-portal/secrets`에는
권한 `600`인 자격증명 파일을 보관합니다. 두 경로 모두 Git 저장소 밖에 있어야 합니다.

### 환경 변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_PATH` | `data/employee_portal.db` | SQLite 파일 경로. Docker에서는 `/app/data/employee_portal.db` |
| `BACKGROUND_CHECK_API_URL` | Swagger의 운영 API 주소 | Background Check 외부 API 기준 URL |
| `BACKGROUND_CHECK_POLLER_ENABLED` | `true` | `false`이면 애플리케이션 내부 폴러를 실행하지 않음 |
| `COOKIE_SECURE` | `false` | HTTPS 운영 환경에서는 반드시 `true`로 설정 |
| `SEED_CREDENTIALS_FILE` | 없음, 필수 | Git 외부에 보관하는 시드 비밀번호 JSON 파일 경로 |

> `BACKGROUND_CHECK_API_URL`의 기본값은 첨부된 Swagger의 실제 외부 서버입니다.
> 기능을 시험하며 Background Check 버튼을 누르면 외부 요청이 발생하므로 허가된 테스트
> 데이터만 사용해야 합니다.

## 시드 계정

아래 계정은 기능 확인을 위한 초기 데이터입니다. 비밀번호는 README와 Git 이력에 포함하지
않고 별도의 자격증명 파일로 전달합니다. 데이터베이스에는 평문 대신 임의 salt를 사용한
`scrypt` 해시만 저장합니다.

| 사번 | 성명 | 성 / 이름 | 역할 | 로그인 아이디 |
|---|---|---|---|---|
| ADM-001 | 시스템관리자 | 시스템 / 관리자 | ADMIN | `admin` |
| EMP-001 | 김민준 | 김 / 민준 | EMPLOYEE | `emp001` |
| EMP-002 | 김민준 | 김 / 민준 | EMPLOYEE | `emp002` |
| EMP-003 | 남궁서준 | 남궁 / 서준 | EMPLOYEE | `emp003` |
| EMP-004 | 황보라온 | 황보 / 라온 | EMPLOYEE | `emp004` |
| EMP-005 | 김솔 | 김 / 솔 | EMPLOYEE | `emp005` |
| EMP-006 | 선우진 | 선 / 우진 | EMPLOYEE | `emp006` |
| EMP-007 | 이서연 | 이 / 서연 | EMPLOYEE | `emp007` |
| EMP-008 | 박민준 | 박 / 민준 | EMPLOYEE | `emp008` |
| EMP-009 | 최지우 | 최 / 지우 | EMPLOYEE | `emp009` |
| EMP-010 | 정하윤 | 정 / 하윤 | EMPLOYEE | `emp010` |

직원 로그인 아이디는 사번에서 실행 중에 역추론하지 않습니다. `Employee.login_id`에
명시적으로 저장되어 있으므로 향후 사번 형식이 바뀌어도 인증 로직은 영향을 받지 않습니다.

새 계정을 만들거나 사용자가 비밀번호를 변경할 때는 8자 이상이며 특수문자를 포함해야
합니다. 시드 자격증명은 더 강한 별도 정책을 적용합니다.

자격증명 파일은 다음 형태이며 `.secrets/`는 Git에서 제외되어 있습니다.

```json
{
  "admin": "별도로 전달하는 비밀번호",
  "emp001": "별도로 전달하는 비밀번호"
}
```

실제 파일에는 `admin`, `emp001`부터 `emp010`까지 11개 로그인 아이디가 모두 필요하며 각
비밀번호는 16자 이상이며 영문 대·소문자, 숫자, 특수문자를 포함해야 합니다. 생성 명령은
이 정책을 만족하는 24자리 무작위 비밀번호와 권한 `600`인 파일을 만들며, 기존 파일이
있으면 덮어쓰지 않고 중단합니다.

### DB 초기화와 자격증명 파일

- 빈 DB로 시작하면 테이블을 만든 뒤 자격증명 파일을 사용해 관리자 1명과 직원 10명을
  생성합니다.
- 기존 DB에서는 같은 사번의 계정을 다시 만들거나 비밀번호를 덮어쓰지 않습니다.
- 기존 DB를 단순히 재시작하는 것만으로는 비밀번호가 변경되지 않습니다.
- 현재 구현은 시작할 때 자격증명 파일의 형식을 검증하므로 기존 DB를 재사용하더라도
  `SEED_CREDENTIALS_FILE`과 읽기 전용 mount가 필요합니다.
- DB 파일을 삭제하고 빈 volume으로 다시 시작하면 현재 자격증명 파일의 값으로 새 계정을
  생성합니다.

### 기존 DB 비밀번호 교체

이미 생성된 DB의 비밀번호를 새 자격증명으로 일괄 교체하려면 먼저 실행 중인 애플리케이션을
중지하고 SQLite 데이터 디렉터리를 백업합니다. 그다음 새 이미지에 운영 DB와 자격증명 파일을
연결하여 일회성 회전 명령을 실행합니다.

```bash
docker run --rm \
  -v /opt/employee-portal/data:/app/data \
  -v /opt/employee-portal/secrets/seed_credentials.json:/run/secrets/seed_credentials.json:ro \
  -e DATABASE_PATH=/app/data/employee_portal.db \
  -e SEED_CREDENTIALS_FILE=/run/secrets/seed_credentials.json \
  employee-portal \
  python -m app.core.rotate_seed_passwords
```

이 명령은 11개 계정의 비밀번호를 다시 해싱하고 모든 활성 세션을 폐기하며, 각 변경을
`CREDENTIAL_EXPOSURE_ROTATION` 사유로 감사로그에 기록한 뒤 하나의 트랜잭션으로 커밋합니다.
도중에 오류가 발생하면 비밀번호 변경과 세션 폐기를 모두 rollback합니다.

교체 후에는 새 자격증명으로 로그인이 성공하고 이전 자격증명으로 로그인이 실패하는지
확인해야 합니다. 비밀번호 파일을 내려받을 때는 SSH/SCP처럼 암호화된 채널을 사용하고,
메신저·이메일·Git으로 전달하지 않습니다.

## 인증과 권한 처리

### 세션 인증

- 로그인 성공 시 `secrets.token_urlsafe(32)`로 예측하기 어려운 세션 ID를 생성합니다.
- 브라우저에는 원본 세션 ID를 `HttpOnly`, `SameSite=Lax` 쿠키로 전달합니다.
- 데이터베이스에는 원본 대신 SHA-256 해시만 저장합니다.
- 세션 기본 유효시간은 8시간입니다.
- HTTPS 환경에서는 `COOKIE_SECURE=true`로 Secure 쿠키를 사용해야 합니다.
- 로그아웃 시 서버 세션을 삭제하고 브라우저 쿠키도 제거합니다.

비밀번호는 Python 표준 라이브러리의 `hashlib.scrypt`로 해싱합니다. 사용자별 임의 salt를
사용하며 검증 결과 비교에는 `hmac.compare_digest`를 사용합니다. 평문 비밀번호는 DB와
감사로그에 저장하지 않습니다.

### 서버 측 인가

- 관리자 라우트는 `require_admin` 의존성으로 `ADMIN` 역할을 검사합니다.
- 일반 직원이 관리자 URL을 직접 요청하면 `403 Forbidden`을 반환합니다.
- 직원 개인정보는 URL 사번이 아니라 현재 세션의 사번으로 조회합니다.
- 화면에서 버튼을 숨기는 것만으로 권한을 대신하지 않습니다.
- 개인정보 변경과 관리자 직접 수정 전 비밀번호를 다시 확인합니다.
- 재확인 권한은 현재 세션에 연결되어 5분간 유효하고 저장 시 한 번만 소비됩니다.

### 퇴사 처리

직원을 삭제하지 않고 `employment_status=TERMINATED`와 `terminated_at`을 기록합니다.
상태 변경, 활성 세션 전체 무효화 및 감사로그를 하나의 DB 트랜잭션으로 커밋합니다.
따라서 이미 브라우저를 열어 둔 직원도 다음 요청부터 즉시 차단되며 다시 로그인할 수 없습니다.

## 개인정보 변경 흐름

직원과 관리자는 자신의 성, 이름, 생년월일을 직접 덮어쓰지 않고 변경 요청을 만듭니다.
관리자 자신이 만든 요청도 다른 관리자가 승인하거나 거절해야 합니다.

```text
현재 비밀번호 확인
  → 변경값 입력
  → PENDING 요청 생성
  → 다른 관리자가 현재값/요청값 비교
  → APPROVED 또는 REJECTED
```

성과 이름은 별도 필드로 비교하므로 `선/우진 → 선우/진`처럼 전체 성명 문자열은 같지만
구분이 달라지는 요청도 관리자가 확인할 수 있습니다. 승인 시 `full_name`은 서버에서
`family_name + given_name`으로 다시 생성합니다.

거절된 요청은 직원 화면에 한 번 표시되며 직원이 닫으면 다시 표시되지 않습니다. 요청,
승인, 거절, 알림 닫기는 모두 감사로그에 남습니다.

## Background Check 설계

Background Check는 응답이 늦고 GET 실패가 자주 발생하며 POST 멱등성이 보장되지 않는 외부
API입니다. 실제 측정 결과를 기준으로 POST와 GET의 실패 정책을 다르게 설계했습니다.

### 외부 API 데이터 변환과 요청 스냅샷

국내 직원 데이터는 `full_name`, `family_name`, `given_name`을 사용하지만 외부 API는
영문 형식의 필드명을 요구합니다.

```text
employeeId  = employee_number
firstName   = submitted_given_name
lastName    = submitted_family_name
dateOfBirth = submitted_date_of_birth
```

Background Check 요청을 생성할 때 다음 값을 요청 메타데이터에 복사합니다.

- `submitted_full_name`
- `submitted_family_name`
- `submitted_given_name`
- `submitted_date_of_birth`

백그라운드 처리기는 외부 POST 직전에 Employee를 다시 조회하지 않고 이 스냅샷만 사용합니다.
따라서 요청 이후 직원의 이름이나 생년월일이 승인 변경되더라도 외부로 전달되는 값은 요청
시점의 값으로 고정됩니다. 관리자는 요청 이력에서 실제 제출값을 확인할 수 있습니다.

### 테이블 분리

Background Check 데이터는 목적과 보존기간에 따라 두 테이블로 분리합니다.

1. `background_check_requests`
   - 업무 상태, 요청자, 요청 사유, 외부 check ID, 요청·완료 시각 및 제출 스냅샷
   - 요청 추적과 감사 가능성을 위한 장기 메타데이터
2. `background_check_results`
   - `request_id`, `CLEAR/FLAGGED`, 생성 시각, 만료 시각만 저장
   - 확인 전까지만 존재하는 임시 결과

외부 API가 반환하는 범죄기록, 신용점수, 학력검증, 경력검증 등의 상세 필드는 모델에
정의하지 않습니다. HTTP 응답에서 필요한 식별자와 상태만 읽으며 나머지는 즉시 버립니다.
상세값은 DB, 화면, 애플리케이션 로그, 감사로그 어디에도 저장하지 않습니다.

### 상태 흐름

```text
REQUESTED
  ├─ POST 결과가 명확함 ─→ PENDING ─→ COMPLETED
  ├─ POST에서 즉시 완료 ─────────────→ COMPLETED
  ├─ POST 결과가 불명확 ─→ SUBMISSION_UNKNOWN ─→ PENDING/COMPLETED
  └─ 명확한 잘못된 요청 ─────────────→ FAILED
```

- `REQUESTED`: 내부 요청이 생성되어 외부 제출을 기다리는 상태
- `SUBMISSION_UNKNOWN`: POST가 외부에 접수됐는지 확정할 수 없는 상태
- `PENDING`: 외부 서비스가 처리 중인 상태
- `COMPLETED`: 최종 결과가 임시 결과 테이블에 저장된 상태
- `FAILED`: 재시도로 회복할 수 없는 명확한 실패 상태

직원 상세 화면은 첫 상태 조회를 2초 뒤에 수행하고 이후 5초 간격으로 우리 서버의 상태 API를
조회합니다. `REQUESTED → PENDING` 등 상태가 변하거나 최종 상태가 되면 페이지를 자동으로
새로고침합니다. 브라우저가 외부 Background Check API를 직접 호출하지는 않습니다.

### POST 비멱등성 대응

동일한 직원으로 POST를 반복하면 서로 다른 외부 `checkId`가 만들어질 수 있으므로 자동 POST
재시도를 하지 않습니다.

- POST timeout: 5초
- 내부 요청 한 건당 자동 POST 시도: 최대 1회
- 응답이 timeout, 네트워크 오류 또는 불명확한 5xx이면 `SUBMISSION_UNKNOWN`
- 같은 직원의 외부 이력을 안전한 GET으로 조회하여 생성 시각과 기존 check ID를 비교
- 후보가 정확히 하나일 때만 해당 요청과 연결
- 후보가 없거나 여러 개면 추측하여 연결하거나 POST를 다시 보내지 않음

이 선택은 일부 요청의 자동 처리가 지연될 수 있는 대신 중복 Background Check 생성 위험을
줄입니다.

### GET 재시도와 폴링

- GET timeout: 요청당 35초
- 500, timeout 및 일반 일시 오류: 5초 후 재시도
- 503: `Retry-After` 헤더, 응답 본문의 `retryAfter`, 30초 기본값 순서로 사용
- 한 요청의 자동 추적시간: 최대 300초
- GET 자동 시도 횟수: 최대 60회
- 외부 API 동시 호출: 최대 5개

측정값은 pending 완료시간 p50 약 158초, p95 약 237초, 최대 약 253초였습니다. 그래서
화면에는 평균 약 3분, 대부분 5분 이내라는 안내를 표시합니다. 5분 안에 끝나지 않아도
Background Check를 실패로 단정하지 않고 자동 빠른 조회만 중지합니다. 관리자는 POST를
다시 보내지 않고 안전한 GET 재확인을 시작할 수 있습니다.

### 중복 요청 차단

다음 상태가 존재하면 같은 직원에 대한 새 요청을 차단합니다.

- `REQUESTED`
- `SUBMISSION_UNKNOWN`
- `PENDING`
- 결과를 아직 파기하지 않은 `COMPLETED`

서비스에서 먼저 검사하고 SQLite 부분 유니크 인덱스에서도 최종 차단합니다. 따라서 화면을
조작하거나 관리자 두 명이 동시에 요청하더라도 미확인 결과가 건너뛰어지지 않습니다.
`FAILED`, 관리자 확인 완료 또는 24시간 TTL 만료 이후에는 새 요청이 가능합니다.

### 결과 열람과 파기

- 결과 열람 전 관리자는 필수 열람 사유를 입력합니다.
- 요청과 열람 사실은 관리자 사번, 대상 사번, 사유 및 시각과 함께 감사됩니다.
- 결과 화면에는 `CLEAR` 또는 `FLAGGED`만 표시합니다.
- 결과 화면 응답에는 `Cache-Control: no-store`를 설정합니다.
- 관리자가 `확인 및 정보파기`를 누르면 임시 결과를 즉시 삭제하고 확인 완료 감사로그를 남깁니다.
- 확인하지 않은 결과도 생성 후 24시간이 지나면 자동 삭제합니다.
- 삭제 메타데이터에는 `ACKNOWLEDGED` 또는 `TTL_EXPIRED` 사유가 남습니다.
- Background Check 결과의 삭제 시점은 직원의 재직 상태나 직원정보 보존기간과 무관합니다.

결과 화면에는 확인 버튼 외의 일반 이동 링크를 제공하지 않아 실수로 확인 절차를 건너뛰는
것을 줄였습니다. 결과가 남아 있는 동안에는 직원 목록에 실제 결과값 대신 `확인 필요`만
표시합니다.

## 민감정보 처리 원칙

- 최소 권한: 관리자 전용 화면과 서버 측 역할 검사로 Background Check 접근 제한
- 목적 제한: 외부 API 응답 중 필요한 최종 상태만 사용
- 최소 저장: 결과 테이블에는 `CLEAR/FLAGGED` 외의 상세 결과를 저장하지 않음
- 짧은 보존: 확인 즉시 또는 생성 24시간 후 임시 결과 삭제
- 캐시 방지: 결과 HTML과 상태 API에 `Cache-Control: no-store`
- 감사 가능성: 요청, 열람, 확인 및 파기 작업을 AuditLog에 기록
- 비밀정보 제외: 비밀번호, 비밀번호 해시 및 Background Check 상세 결과는 감사로그에 기록하지 않음
- 자격증명 분리: 시드 비밀번호 파일은 Git과 Docker build context에서 제외하고 컨테이너에 읽기 전용 mount
- 세션 통제: 퇴사 및 보안 관련 계정 변경 시 기존 세션 즉시 무효화
- 개인정보 스냅샷: 요청 당시 전송값은 관리자 전용 요청 메타데이터에만 보관하고 감사로그에는 복사하지 않음

SQLite 파일 자체는 애플리케이션 수준에서 암호화하지 않습니다. 운영 환경에서는 EC2와
volume 접근 권한을 최소화하고, 암호화된 EBS, HTTPS, 안전한 백업 및 로그 접근통제를 함께
적용해야 합니다.

## 감사로그 대상 작업

- 직원 생성 및 관리자 직접 수정
- 직원 퇴사 처리
- 개인정보 변경 요청, 승인, 거절 및 거절 알림 확인
- 비밀번호 변경
- Background Check 요청, 결과 열람, 확인 및 파기

직원 상태 변경, 세션 무효화, 결과 삭제와 대응하는 감사로그는 가능한 경우 같은 DB
트랜잭션으로 처리합니다. 중간 오류가 발생하면 전체를 rollback하여 상태와 감사기록이 서로
어긋나지 않게 합니다.

## 테스트

```bash
pytest -q
```

테스트 DB는 운영 DB와 분리된 임시 SQLite 파일을 사용하고 Background Check 내부 폴러는
비활성화합니다. Fake Client로 다음 항목을 포함해 검증합니다.

- 로그인, 역할 및 소유권 검사
- 퇴사 처리와 즉시 세션 차단
- 직원 생성·수정·정보 변경 요청과 감사로그의 트랜잭션 처리
- 요청 스냅샷과 한글 복성 매핑
- POST 1회 원칙과 불명확 제출 reconciliation
- GET 재시도, `Retry-After`, 5분 추적 제한과 최대 동시 호출 수
- 미확인 결과 중복 요청 차단과 DB 유니크 인덱스
- 확인 즉시 삭제와 24시간 TTL
- 상세 민감정보 비저장
- 기존 SQLite 스키마 마이그레이션

현재 전체 테스트 결과는 `20 passed`입니다.

## 현재 범위와 운영 시 고려사항

이 프로젝트는 소규모 과제를 위한 단일 프로세스 구조입니다. SQLite와 애플리케이션 내부
폴러를 함께 사용하므로 `--workers 1`을 전제로 합니다. 여러 인스턴스나 여러 worker로
확장할 경우 PostgreSQL 같은 서버형 DB와 별도 작업 큐 및 단일 스케줄러로 폴러를 분리하는
것이 적절합니다.

실제 운영에서는 HTTPS와 Secure 쿠키 강제, CSRF 보호, 비밀값 관리, EBS 암호화, 접근 로그
정책과 백업·복구 절차를 추가로 점검해야 합니다. 자격증명 파일과 DB 백업도 개인정보로
분류하여 최소 인원만 접근할 수 있게 관리해야 합니다.
