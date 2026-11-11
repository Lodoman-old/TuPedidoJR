"""Tests for push notification configuration and token registration."""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.security import decode_access_token
from app.models.setting import Setting
from app.models.user import User


@pytest.fixture
async def normal_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Push User", "email": "push@test.com", "password": "pass123",
    })
    return resp.json()["access_token"]


@pytest.fixture
async def superuser_token(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/auth/register", json={
        "name": "Push Admin", "email": "pushadmin@test.com", "password": "pass123",
    })
    token = resp.json()["access_token"]
    user_id = decode_access_token(token)["sub"]
    user = await db_session.get(User, user_id)
    user.is_superuser = True
    await db_session.commit()
    return token


class TestPushConfig:
    async def test_public_config(self, client: AsyncClient):
        resp = await client.get("/api/v1/push/config")
        assert resp.status_code == 200
        assert "enabled" in resp.json()
        assert "android_config" in resp.json()

    async def test_admin_config_forbidden_for_normal_user(
        self, client: AsyncClient, normal_token,
    ):
        resp = await client.get(
            "/api/v1/push/admin/config",
            headers={"Authorization": f"Bearer {normal_token}"},
        )
        assert resp.status_code == 403

    async def test_admin_can_save_config(self, client: AsyncClient, superuser_token):
        headers = {"Authorization": f"Bearer {superuser_token}"}
        service_account = json.dumps({
            "client_email": "demo@demo.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----",
            "project_id": "demo-project",
        })
        web_config = json.dumps({"apiKey": "x", "projectId": "demo-project"})
        android_config = json.dumps({
            "project_id": "demo-project",
            "mobilesdk_app_id": "1:1:android:abc",
            "api_key": "AIza-demo",
            "gcm_defaultSenderId": "1",
        })

        resp = await client.put(
            "/api/v1/push/admin/config",
            headers=headers,
            json={
                "enabled": True,
                "service_account_json": service_account,
                "web_config_json": web_config,
                "android_config_json": android_config,
                "vapid_key": "Bdemo",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["has_service_account"] is True
        assert data["project_id"] == "demo-project"
        assert data["android_config"]["mobilesdk_app_id"] == "1:1:android:abc"

        public = await client.get("/api/v1/push/config")
        assert public.json()["enabled"] is True
        assert public.json()["vapid_key"] == "Bdemo"

        # Clean up so other tests do not try to send notifications.
        await client.put(
            "/api/v1/push/admin/config",
            headers=headers,
            json={"enabled": False},
        )

    async def test_cannot_enable_without_service_account(
        self, client: AsyncClient, superuser_token, db_session,
    ):
        await db_session.execute(
            delete(Setting).where(Setting.key == "FCM_SERVICE_ACCOUNT_JSON")
        )
        await db_session.commit()
        resp = await client.put(
            "/api/v1/push/admin/config",
            headers={"Authorization": f"Bearer {superuser_token}"},
            json={"enabled": True},
        )
        assert resp.status_code == 400


class TestPushTokens:
    async def test_register_requires_auth(self, client: AsyncClient):
        resp = await client.post("/api/v1/push/tokens", json={"token": "abc1234567890"})
        assert resp.status_code == 401

    async def test_register_and_unregister(self, client: AsyncClient, normal_token):
        headers = {"Authorization": f"Bearer {normal_token}"}
        body = {"token": "device-token-1234567890", "platform": "android", "device_label": "Pixel"}
        resp = await client.post("/api/v1/push/tokens", headers=headers, json=body)
        assert resp.status_code == 201

        # Registering the same token again updates it instead of failing.
        resp = await client.post("/api/v1/push/tokens", headers=headers, json=body)
        assert resp.status_code == 201

        resp = await client.delete(
            "/api/v1/push/tokens",
            headers=headers,
            params={"token": body["token"]},
        )
        assert resp.status_code == 204
