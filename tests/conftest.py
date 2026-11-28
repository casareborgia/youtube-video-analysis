"""테스트가 운영 데이터를 건드리지 못하게 막는다.

아래 경로들은 모듈 상수로 박혀 있어서, 따로 바꿔 주지 않은 테스트는 실행 폴더의 진짜 파일에 쓴다.
실제로 그랬다: 실행 폴더에서 테스트를 돌릴 때마다 운영 DB 에 TEST_TOPIC_1 같은 발송 작업이 쌓였고,
AI_TREND 루틴이 AUTO 로 바뀌었고, data/x_config.json 의 access_token 이 테스트 값으로 덮였다.

pytest 는 테스트 모듈보다 이 파일을 먼저 읽는다. 여기서 상수를 임시 폴더로 돌려 두면
`from app import app` 이 만드는 모듈 수준 객체(api.autonomous_routes.repo 등)도 임시 파일을 쓴다.
상수를 스스로 patch 하는 테스트는 그대로 동작하고, 끝나면 이 임시 경로로 돌아온다.
"""

import atexit
import shutil
import tempfile
from pathlib import Path

import pytest

import engagement_automation
import prompt_generator
import social_store
import threads_client
import x_client
from repositories import routine_repository

SANDBOX = Path(tempfile.mkdtemp(prefix="tubeinsight_tests_"))
atexit.register(shutil.rmtree, SANDBOX, ignore_errors=True)

# (모듈, 상수 이름, 임시 폴더 안의 이름, 문자열 경로 여부)
REDIRECTS = [
    (routine_repository, "DEFAULT_DB_PATH", "autonomous_operator.db", True),
    (social_store, "DEFAULT_DB_PATH", "social_engagement.db", False),
    (engagement_automation, "DB_PATH", "social_engagement.db", False),
    (x_client, "CONFIG_FILE", "x_config.json", False),
    (threads_client, "CONFIG_FILE", "threads_config.json", False),
    (prompt_generator, "OUTPUT_DIR", "output", False),
]

# 운영 경로를 기억해 둔다. 격리가 풀렸는지 확인하는 테스트가 쓴다.
REAL_PATHS = {
    f"{module.__name__}.{name}": Path(getattr(module, name)) for module, name, _, _ in REDIRECTS
}

for module, name, leaf, as_text in REDIRECTS:
    target = SANDBOX / leaf
    setattr(module, name, str(target) if as_text else target)

(SANDBOX / "output").mkdir(exist_ok=True)


@pytest.fixture(scope="session")
def sandbox_dir() -> Path:
    return SANDBOX


@pytest.fixture(scope="session")
def real_paths() -> dict:
    return dict(REAL_PATHS)
