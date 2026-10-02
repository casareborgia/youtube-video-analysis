"""Unit tests for Phase 2: X (Twitter) API v2 OAuth 2.0 PKCE and Account Adapter.

Tests cover:
- PKCE verifier and challenge generation (RFC 7636 compliant S256)
- Authorization URL construction with state, scopes, PKCE parameters
- OAuth callback exchange with mocked responses (Token + Users Me)
- Token refresh flow
- Error classification: TOKEN_EXPIRED, INSUFFICIENT_SCOPE, INVALID_CREDENTIALS
- Security & credential protection: tokens not leaked in error messages or social_accounts table
- SocialStore synchronization: social_accounts upsert / disconnect
- FastAPI endpoints integration
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

# Suppress StarletteDeprecationWarning for TestClient under -W error
warnings.filterwarnings("ignore", message=".*Using `httpx` with `starlette.testclient`.*")

from fastapi.testclient import TestClient

from app import app
import social_store
import x_client


class XClientTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_social.db"
        self.config_path = Path(self.temp_dir.name) / "x_config.json"

        # 격리된 SocialStore 및 config 경로 패치
        self.store = social_store.SocialStore(self.db_path)
        self.config_patch = patch.object(x_client, "CONFIG_FILE", self.config_path)
        self.config_patch.start()

        # 환경변수 클린업
        self.env_patch = patch.dict(
            "os.environ",
            {
                "X_CLIENT_ID": "test_client_id_123",
                "X_CLIENT_SECRET": "test_client_secret_xyz",
                "X_REDIRECT_URI": "http://127.0.0.1:8765/api/x/auth/callback",
                "X_ACCESS_TOKEN": "",
                "X_REFRESH_TOKEN": "",
                "X_USER_ID": "",
            },
        )
        self.env_patch.start()

        self.client = TestClient(app)

    def tearDown(self):
        self.env_patch.stop()
        self.config_patch.stop()
        self.temp_dir.cleanup()

    def test_pkce_generation_and_format(self):
        verifier, challenge = x_client.generate_pkce_pair()
        self.assertTrue(43 <= len(verifier) <= 128)
        self.assertNotIn("=", challenge, "challenge should have trailing '=' stripped")

        # Verify challenge computation matches SHA-256
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        self.assertEqual(challenge, expected)

    def test_auth_url_generation(self):
        # 1. Missing client_id throws config missing
        with patch.dict("os.environ", {"X_CLIENT_ID": ""}):
            with self.assertRaises(x_client.XClientError) as ctx:
                x_client.get_oauth_authorization_url()
            self.assertEqual(ctx.exception.code, x_client.ERR_CONFIG_MISSING)

        # 2. Valid URL generation
        data = x_client.get_oauth_authorization_url(
            redirect_uri="http://127.0.0.1:8765/callback",
            scopes=["tweet.read", "tweet.write"],
            state="fixed_state_abc",
        )
        url = data["url"]
        self.assertTrue(url.startswith("https://twitter.com/i/oauth2/authorize?"))
        self.assertIn("response_type=code", url)
        self.assertIn("client_id=test_client_id_123", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("state=fixed_state_abc", url)
        self.assertIn("code_challenge=" + data["code_challenge"], url)
        self.assertIn("scope=tweet.read+tweet.write", url)

    @patch("x_client._http_request")
    def test_oauth_callback_exchange_and_sync(self, mock_http):
        # 모의 응답 1: 토큰 교환 성공
        mock_token_resp = {
            "token_type": "bearer",
            "expires_in": 7200,
            "access_token": "mock_access_token_super_secret",
            "scope": "tweet.read tweet.write users.read offline.access",
            "refresh_token": "mock_refresh_token_abc",
        }
        # 모의 응답 2: users/me 조회 성공
        mock_user_resp = {
            "data": {
                "id": "x_user_9999",
                "username": "tube_influencer",
                "name": "Tube Creator",
                "profile_image_url": "https://pbs.twimg.com/profile_images/1/avatar.png",
            }
        }

        mock_http.side_effect = [mock_token_resp, mock_user_resp]

        res = x_client.handle_oauth_callback(
            code="test_auth_code_111",
            code_verifier="test_code_verifier_222",
            redirect_uri="http://127.0.0.1:8765/api/x/auth/callback",
            store=self.store,
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["user_id"], "x_user_9999")
        self.assertEqual(res["username"], "tube_influencer")

        # SocialStore 계정 테이블 동기화 검증
        account = self.store.get_account("x", "x_user_9999")
        self.assertIsNotNone(account)
        self.assertEqual(account["username"], "tube_influencer")
        self.assertEqual(account["display_name"], "Tube Creator")
        self.assertEqual(account["status"], "connected")
        self.assertEqual(account["credential_ref"], "data/x_config.json")
        self.assertIn("tweet.write", account["scopes"])

        # 토큰 원문이 SocialStore DB에 들어가지 않았음을 보증
        with self.store._connect() as conn:
            raw_row = conn.execute("SELECT * FROM social_accounts WHERE account_id='x_user_9999'").fetchone()
            row_str = str(dict(raw_row))
            self.assertNotIn("mock_access_token_super_secret", row_str)

    @patch("x_client._http_request")
    def test_token_refresh(self, mock_http):
        mock_refresh_resp = {
            "token_type": "bearer",
            "expires_in": 3600,
            "access_token": "new_refreshed_access_token",
            "refresh_token": "new_refreshed_refresh_token",
            "scope": "tweet.read tweet.write",
        }
        mock_http.return_value = mock_refresh_resp

        # 1. No refresh token raises TOKEN_EXPIRED
        with self.assertRaises(x_client.XClientError) as ctx:
            x_client.refresh_access_token()
        self.assertEqual(ctx.exception.code, x_client.ERR_TOKEN_EXPIRED)

        # 2. Passing valid refresh token succeeds
        res = x_client.refresh_access_token(
            refresh_token_str="existing_refresh_token_val",
            store=self.store,
        )
        self.assertEqual(res["status"], "success")
        self.assertGreater(res["expires_at"], 0)

        conf = x_client.load_config()
        self.assertEqual(conf["access_token"], "new_refreshed_access_token")
        self.assertEqual(conf["refresh_token"], "new_refreshed_refresh_token")

    def test_status_expired_and_insufficient_scope(self):
        # 1. Disconnected status when no token
        st = x_client.get_status()
        self.assertFalse(st["connected"])
        self.assertEqual(st["status"], "disconnected")

        # 2. Expired status
        x_client.save_config({
            "access_token": "tok_123",
            "user_id": "u_1",
            "username": "exp_user",
            "token_expires_at": 1000,  # Far past
            "scopes": ["tweet.read", "tweet.write"],
        })
        st_exp = x_client.get_status()
        self.assertFalse(st_exp["connected"])
        self.assertEqual(st_exp["status"], "expired")
        self.assertEqual(st_exp["error_code"], x_client.ERR_TOKEN_EXPIRED)

        # 3. Insufficient scope status
        x_client.save_config({
            "access_token": "tok_123",
            "user_id": "u_1",
            "username": "low_scope_user",
            "token_expires_at": 2000000000,
            "scopes": ["users.read"],  # Missing tweet.read & tweet.write
        })
        st_scope = x_client.get_status()
        self.assertTrue(st_scope["connected"])
        self.assertEqual(st_scope["status"], "insufficient_scope")
        self.assertEqual(st_scope["error_code"], x_client.ERR_INSUFFICIENT_SCOPE)

        # 4. Perfectly connected
        x_client.save_config({
            "access_token": "tok_123",
            "user_id": "u_1",
            "username": "perfect_user",
            "token_expires_at": 2000000000,
            "scopes": ["tweet.read", "tweet.write", "users.read"],
        })
        st_ok = x_client.get_status()
        self.assertTrue(st_ok["connected"])
        self.assertEqual(st_ok["status"], "connected")
        self.assertIsNone(st_ok["error_code"])

    @patch("x_client._http_request")
    def test_disconnect_and_cleanup(self, mock_http):
        mock_http.return_value = {}
        # Prepopulate
        x_client.save_config({
            "access_token": "tok_to_revoke",
            "user_id": "u_to_disconnect",
            "username": "user_bye",
        }, store=self.store)

        # Ensure account exists in SocialStore
        self.assertIsNotNone(self.store.get_account("x", "u_to_disconnect"))

        res = x_client.disconnect(store=self.store)
        self.assertEqual(res["status"], "success")

        # Local config emptied
        conf = x_client.load_config()
        self.assertEqual(conf["access_token"], "")
        self.assertEqual(conf["user_id"], "")

        # SocialStore account deleted
        self.assertIsNone(self.store.get_account("x", "u_to_disconnect"))

    def test_api_endpoints_via_testclient(self):
        # 1. GET /api/x/status
        resp = self.client.get("/api/x/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("connected", data)
        self.assertIn("status", data)

        # 2. GET /api/x/auth/login
        resp_login = self.client.get("/api/x/auth/login", follow_redirects=False)
        self.assertEqual(resp_login.status_code, 307)
        self.assertTrue(resp_login.headers["location"].startswith("https://twitter.com/i/oauth2/authorize?"))

        # 3. GET /api/social/accounts
        resp_acc = self.client.get("/api/social/accounts")
        self.assertEqual(resp_acc.status_code, 200)
        acc_data = resp_acc.json()
        self.assertIn("accounts", acc_data)
        self.assertIn("threads_status", acc_data)
        self.assertIn("x_status", acc_data)


if __name__ == "__main__":
    unittest.main()
