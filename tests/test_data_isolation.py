"""테스트 실행이 운영 데이터 파일을 열지 않는지 확인한다 (tests/conftest.py 가 지키는 약속)."""

from pathlib import Path

import engagement_automation
import prompt_generator
import social_store
import threads_client
import x_client
from repositories import routine_repository
from repositories.routine_repository import RoutineRepository


def _inside(path, folder: Path) -> bool:
    return folder.resolve() in Path(path).resolve().parents


def test_path_constants_point_into_the_sandbox(sandbox_dir, real_paths):
    current = {
        "repositories.routine_repository.DEFAULT_DB_PATH": routine_repository.DEFAULT_DB_PATH,
        "social_store.DEFAULT_DB_PATH": social_store.DEFAULT_DB_PATH,
        "engagement_automation.DB_PATH": engagement_automation.DB_PATH,
        "x_client.CONFIG_FILE": x_client.CONFIG_FILE,
        "threads_client.CONFIG_FILE": threads_client.CONFIG_FILE,
        "prompt_generator.OUTPUT_DIR": prompt_generator.OUTPUT_DIR,
    }
    assert set(current) == set(real_paths)
    for name, path in current.items():
        assert _inside(path, sandbox_dir), f"{name} 이 임시 폴더 밖을 가리킨다: {path}"
        assert Path(path).resolve() != real_paths[name].resolve()


def test_default_repository_opens_the_sandbox_db(sandbox_dir, real_paths):
    repo = RoutineRepository()
    assert _inside(repo.db_path, sandbox_dir)
    assert Path(repo.db_path).resolve() != real_paths["repositories.routine_repository.DEFAULT_DB_PATH"].resolve()


def test_route_singletons_use_the_sandbox_db(sandbox_dir):
    # app 을 불러올 때 만들어지는 모듈 수준 저장소. 여기가 운영 DB 를 열면 라우트 테스트가 운영 DB 에 쓴다.
    from api import autonomous_routes

    assert _inside(autonomous_routes.repo.db_path, sandbox_dir)
    assert _inside(autonomous_routes.orchestrator.repo.db_path, sandbox_dir)


def test_default_stores_open_the_sandbox(sandbox_dir):
    assert _inside(social_store.SocialStore().path, sandbox_dir)
    assert _inside(engagement_automation.EngagementStore().path, sandbox_dir)


def test_explicit_path_still_wins(tmp_path):
    repo = RoutineRepository(db_path=str(tmp_path / "own.db"))
    assert Path(repo.db_path) == tmp_path / "own.db"
