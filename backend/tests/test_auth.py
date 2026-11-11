"""Tests for auth endpoints: register, login, me."""

import pytest
from httpx import AsyncClient


class TestRegister:
    def _payload(self, **kwargs):
        return {
            "name": "Test User",
            "email": "test@example.com",
            "phone": "555-9999",
            "password": "secret123",
            **kwargs,
        }

    async def test_register_success(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json=self._payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 20
        assert data["expires_in"] > 0

    async def test_register_duplicate_email(self, client: AsyncClient):
        await client.post("/api/v1/auth/register", json=self._payload())
        resp = await client.post("/api/v1/auth/register", json=self._payload())
        assert resp.status_code == 409
        assert "registrado" in resp.json()["detail"]

    async def test_register_invalid_email(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json=self._payload(email="not-an-email"))
        assert resp.status_code == 422


class TestLogin:
    async def _register_user(self, client: AsyncClient, email="login@test.com"):
        await client.post("/api/v1/auth/register", json={
            "name": "Login Test", "email": email,
            "password": "password123",
        })

    async def test_login_success(self, client: AsyncClient):
        await self._register_user(client)
        resp = await client.post("/api/v1/auth/login", json={
            "email": "login@test.com", "password": "password123",
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_login_wrong_password(self, client: AsyncClient):
        await self._register_user(client)
        resp = await client.post("/api/v1/auth/login", json={
            "email": "login@test.com", "password": "wrongpass",
        })
        assert resp.status_code == 401

    async def test_login_user_not_found(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "noone@test.com", "password": "password123",
        })
        assert resp.status_code == 401


class TestMe:
    async def test_me_with_token(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "name": "Me Test", "email": "me@test.com", "password": "password123",
        })
        token = resp.json()["access_token"]

        resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Me Test"
        assert data["email"] == "me@test.com"
        assert "id" in data

    async def test_me_no_token(self, client: AsyncClient):
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_me_invalid_token(self, client: AsyncClient):
        resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid"})
        assert resp.status_code == 401
