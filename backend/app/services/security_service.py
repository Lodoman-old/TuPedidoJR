"""Protección contra escaneos, scraping y abuso.

Mantiene contadores en memoria (rápido, sin tocar la base en cada visita)
y solo escribe en la base cuando detecta un evento o bloquea una IP.
"""

from __future__ import annotations

import ipaddress
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.security import BlockedIP, SecurityEvent
from app.services.order_service import get_setting_value

WINDOW_SECONDS = 60
SCORE_WINDOW_SECONDS = 600
MAX_TRACKED_IPS = 5000

SUSPICIOUS_PATHS = re.compile(
    r"("
    r"\.env|\.git|\.svn|\.aws|\.ssh|\.DS_Store|"
    r"/wp-admin|/wp-login|/wp-content|/wp-includes|/wp-json|/xmlrpc\.php|/wordpress|"
    r"/phpmyadmin|/pma/|/adminer|/myadmin|/mysql|/db\.php|/sql\.php|"
    r"/vendor/|/config\.|/configuration|/\.idea|/\.vscode|"
    r"/etc/passwd|/proc/self|boot\.ini|/windows/win\.ini|"
    r"/cgi-bin/|/shell|/eval\(|/cmd\.php|/backdoor|/webshell|"
    r"/actuator|/server-status|/server-info|/manager/html|/host-manager|"
    r"/solr/|/jenkins|/hudson|/zabbix|/druid/|/nacos|/_ignition|/telescope|"
    r"/HNAP1|/boaform|/setup\.cgi|/login\.cgi|/owa/|/autodiscover|"
    r"/joomla|/typo3|/drupal|/magento|/prestashop|"
    r"\.\./|%2e%2e|%252e|/\.\./"
    r")",
    re.IGNORECASE,
)

INJECTION_PATTERNS = re.compile(
    r"("
    r"union\s+(all\s+)?select|select\s+.*\s+from\s+information_schema|"
    r"'\s*or\s+'?1'?\s*=\s*'?1|or\s+1\s*=\s*1|sleep\s*\(\s*\d|benchmark\s*\(|"
    r"<script|javascript:|onerror\s*=|onload\s*=|"
    r"\$\{jndi:|/bin/(ba)?sh|nc\s+-e|wget\s+http|curl\s+http"
    r")",
    re.IGNORECASE,
)

SKIP_COUNT_PREFIXES = ("/static/", "/tiles/", "/health", "/favicon.ico", "/robots.txt")
NEVER_AUTO_BLOCK_PREFIXES = ("/web/admin",)


@dataclass
class Decision:
    blocked: bool = False
    reason: str = ""


def client_ip(request: Request) -> str:
    """IP real detrás de Traefik/Coolify (la última del X-Forwarded-For)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if parts:
            return parts[-1]
    real = request.headers.get("x-real-ip")
    if real and real.strip():
        return real.strip()
    return request.client.host if request.client else "desconocida"


def is_valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address((value or "").strip())
        return True
    except ValueError:
        return False


def _is_local(ip: str) -> bool:
    """Loopback o red privada: tráfico interno del servidor/proxy."""
    try:
        address = ipaddress.ip_address(ip)
        return address.is_loopback or address.is_private
    except ValueError:
        return False


def matches_network(ip: str, network: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(network.strip(), strict=False)
    except ValueError:
        return False


def is_suspicious_path(raw: str) -> bool:
    value = raw or ""
    return bool(SUSPICIOUS_PATHS.search(value) or INJECTION_PATTERNS.search(value))


class SecurityGuard:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._score: dict[str, deque[tuple[float, int, str]]] = {}
        self._not_found: dict[str, deque[float]] = {}
        self._blocked: dict[str, float] = {}
        self._last_hit_log: dict[str, float] = {}
        self._session_factory = None
        self._settings: dict = {}
        self._settings_at = 0.0
        self._whitelist: list[str] = []

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------
    def configure(self, session_factory) -> None:
        """Usa la misma sesión de base que la app (o la de pruebas)."""
        self._session_factory = session_factory

    def _session(self):
        factory = self._session_factory or async_session
        return factory()

    async def _refresh_settings(self, force: bool = False) -> dict:
        now = time.time()
        if not force and self._settings and now - self._settings_at < 30:
            return self._settings
        values = {
            "enabled": "true",
            "auto_block": "true",
            "rate_limit": "400",
            "block_minutes": "60",
            "whitelist": "",
        }
        try:
            async with self._session() as db:
                values["enabled"] = await get_setting_value(db, "SECURITY_ENABLED", "true")
                values["auto_block"] = await get_setting_value(db, "SECURITY_AUTO_BLOCK", "true")
                values["rate_limit"] = await get_setting_value(
                    db, "SECURITY_RATE_LIMIT_PER_MIN", "400"
                )
                values["block_minutes"] = await get_setting_value(
                    db, "SECURITY_BLOCK_MINUTES", "60"
                )
                values["whitelist"] = await get_setting_value(db, "SECURITY_WHITELIST", "")
        except Exception:
            pass
        self._settings = values
        self._settings_at = now
        self._whitelist = [
            item.strip() for item in str(values.get("whitelist") or "").split(",") if item.strip()
        ]
        return values

    def reset_settings_cache(self) -> None:
        self._settings_at = 0.0

    async def refresh_settings(self, force: bool = True) -> dict:
        return await self._refresh_settings(force=force)

    def reset(self) -> None:
        """Limpia el estado en memoria (pruebas y reinicios)."""
        self._hits.clear()
        self._score.clear()
        self._not_found.clear()
        self._blocked.clear()
        self._last_hit_log.clear()
        self._settings.clear()
        self._settings_at = 0.0
        self._whitelist = []

    # ------------------------------------------------------------------
    # Bloqueos
    # ------------------------------------------------------------------
    async def load_blocks(self) -> None:
        try:
            now = datetime.now(timezone.utc)
            async with self._session() as db:
                result = await db.execute(select(BlockedIP))
                for row in result.scalars().all():
                    if row.expires_at is not None and row.expires_at <= now:
                        continue
                    self._blocked[row.ip] = (
                        row.expires_at.timestamp()
                        if row.expires_at is not None
                        else now.timestamp() + 365 * 86400
                    )
        except Exception:
            pass

    def is_blocked(self, ip: str) -> bool:
        expires = self._blocked.get(ip)
        if not expires:
            return False
        if expires <= time.time():
            self._blocked.pop(ip, None)
            return False
        return True

    async def block(
        self,
        ip: str,
        minutes: float,
        reason: str,
        detail: str | None = None,
        path: str | None = None,
        auto: bool = True,
    ) -> None:
        if not is_valid_ip(ip):
            return
        minutes = max(1.0, min(float(minutes), 10080.0))
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        self._blocked[ip] = expires_at.timestamp()
        try:
            async with self._session() as db:
                existing = (
                    await db.execute(select(BlockedIP).where(BlockedIP.ip == ip))
                ).scalar_one_or_none()
                if existing:
                    existing.reason = reason
                    existing.detail = detail
                    existing.path = path
                    existing.auto = auto
                    existing.expires_at = expires_at
                else:
                    db.add(
                        BlockedIP(
                            ip=ip,
                            reason=reason,
                            detail=detail,
                            path=path,
                            auto=auto,
                            expires_at=expires_at,
                        )
                    )
                db.add(
                    SecurityEvent(
                        ip=ip,
                        kind="block",
                        path=(path or "")[:400] or None,
                        detail=detail or reason,
                        blocked=True,
                    )
                )
                await db.commit()
        except Exception:
            pass

    async def unblock(self, ip: str, detail: str | None = None) -> bool:
        self._blocked.pop(ip, None)
        try:
            async with self._session() as db:
                existing = (
                    await db.execute(select(BlockedIP).where(BlockedIP.ip == ip))
                ).scalar_one_or_none()
                if existing:
                    await db.delete(existing)
                db.add(SecurityEvent(ip=ip, kind="unblock", detail=detail, blocked=False))
                await db.commit()
        except Exception:
            pass
        return True

    # ------------------------------------------------------------------
    # Eventos
    # ------------------------------------------------------------------
    async def record(
        self,
        ip: str,
        kind: str,
        path: str | None = None,
        method: str | None = None,
        user_agent: str | None = None,
        detail: str | None = None,
        blocked: bool = False,
    ) -> None:
        try:
            async with self._session() as db:
                db.add(
                    SecurityEvent(
                        ip=ip[:64],
                        kind=kind[:40],
                        path=(path or "")[:400] or None,
                        method=(method or "")[:10] or None,
                        user_agent=(user_agent or "")[:400] or None,
                        detail=detail,
                        blocked=blocked,
                    )
                )
                await db.commit()
        except Exception:
            pass

    def _add_score(self, ip: str, points: int, reason: str) -> int:
        now = time.time()
        queue = self._score.setdefault(ip, deque())
        queue.append((now, points, reason))
        while queue and now - queue[0][0] > SCORE_WINDOW_SECONDS:
            queue.popleft()
        return sum(item[1] for item in queue)

    def _rate_exceeded(self, ip: str, limit: int) -> bool:
        now = time.time()
        hits = self._hits.setdefault(ip, deque())
        hits.append(now)
        while hits and now - hits[0] > WINDOW_SECONDS:
            hits.popleft()
        if len(self._hits) > MAX_TRACKED_IPS:
            for key in list(self._hits)[:1000]:
                if key != ip:
                    self._hits.pop(key, None)
        return len(hits) > limit

    def _too_many_404(self, ip: str, threshold: int = 30) -> bool:
        now = time.time()
        hits = self._not_found.setdefault(ip, deque())
        while hits and now - hits[0] > 300:
            hits.popleft()
        return len(hits) > threshold

    async def observe_response(self, request: Request, status_code: int) -> None:
        path = request.url.path
        if path.startswith(SKIP_COUNT_PREFIXES):
            return
        ip = client_ip(request)
        if _is_local(ip) and not request.headers.get("x-forwarded-for"):
            return
        settings = await self._refresh_settings()
        if str(settings.get("enabled")).lower() not in {"1", "true", "yes", "si", "sí", "on"}:
            return
        if path.startswith("/api/v1/auth/login") and status_code in (400, 401, 403):
            points = self._add_score(ip, 30, "brute_force")
            await self.record(ip, "brute_force", path, request.method, detail=f"Intento de acceso fallido ({status_code})")
            if points >= 100:
                await self._auto_block(ip, "brute_force", path, "Intentos repetidos de iniciar sesión")
            return
        if status_code == 404:
            self._not_found.setdefault(ip, deque()).append(time.time())
            if self._too_many_404(ip):
                await self.record(ip, "scan", path, request.method, detail="Ráfaga de rutas inexistentes")
                await self._auto_block(ip, "scan", path, "Ráfaga de rutas inexistentes (escaneo)")

    async def _auto_block(self, ip: str, reason: str, path: str, detail: str) -> None:
        settings = await self._refresh_settings()
        if str(settings.get("auto_block")).lower() not in {"1", "true", "yes", "si", "sí", "on"}:
            return
        if path.startswith(NEVER_AUTO_BLOCK_PREFIXES):
            return
        try:
            minutes = float(settings.get("block_minutes") or 60)
        except (TypeError, ValueError):
            minutes = 60.0
        self._score.pop(ip, None)
        await self.block(ip, minutes, reason, detail=detail, path=path, auto=True)

    # ------------------------------------------------------------------
    # Inspección
    # ------------------------------------------------------------------
    async def inspect(self, request: Request) -> Decision:
        ip = client_ip(request)
        path = request.url.path
        query = request.url.query
        full = f"{path}?{query}" if query else path

        if not is_valid_ip(ip):
            return Decision(False)

        if _is_local(ip) and not request.headers.get("x-forwarded-for"):
            return Decision(False)

        settings = await self._refresh_settings()
        enabled = str(settings.get("enabled")).lower() in {"1", "true", "yes", "si", "sí", "on"}
        if not enabled:
            return Decision(False)

        if self._whitelist and any(matches_network(ip, item) for item in self._whitelist):
            return Decision(False)

        if self.is_blocked(ip):
            now = time.time()
            if now - self._last_hit_log.get(ip, 0) > 300:
                self._last_hit_log[ip] = now
                await self.record(ip, "blocked_hit", path, request.method, detail="Solicitud rechazada: IP bloqueada", blocked=True)
            return Decision(True, "IP bloqueada temporalmente")

        if is_suspicious_path(full):
            await self.record(ip, "scan", path, request.method, request.headers.get("user-agent"), detail="Ruta o parámetro sospechoso")
            await self._auto_block(ip, "scan", path, "Intento de escaneo o inyección")
            return Decision(True if self.is_blocked(ip) else False, "Intento de escaneo")

        if path.startswith(SKIP_COUNT_PREFIXES):
            return Decision(False)

        try:
            limit = int(float(settings.get("rate_limit") or 400))
        except (TypeError, ValueError):
            limit = 400
        if limit > 0 and self._rate_exceeded(ip, limit):
            await self.record(ip, "rate", path, request.method, detail=f"Más de {limit} solicitudes por minuto")
            await self._auto_block(ip, "rate", path, f"Tráfico excesivo ({limit}/min)")
            return Decision(True if self.is_blocked(ip) else False, "Tráfico excesivo")

        return Decision(False)


security_guard = SecurityGuard()


async def list_security_overview(db: AsyncSession) -> dict:
    """Datos para la página del administrador."""
    from sqlalchemy import func

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    total = await db.scalar(
        select(func.count(SecurityEvent.id)).where(SecurityEvent.created_at >= since)
    )
    by_kind = await db.execute(
        select(SecurityEvent.kind, func.count(SecurityEvent.id))
        .where(SecurityEvent.created_at >= since)
        .group_by(SecurityEvent.kind)
    )
    counters = {row[0]: row[1] for row in by_kind.all()}
    blocks = await db.execute(
        select(BlockedIP).order_by(BlockedIP.created_at.desc()).limit(100)
    )
    events = await db.execute(
        select(SecurityEvent).order_by(SecurityEvent.created_at.desc()).limit(120)
    )
    top = await db.execute(
        select(SecurityEvent.ip, func.count(SecurityEvent.id))
        .where(SecurityEvent.created_at >= since)
        .group_by(SecurityEvent.ip)
        .order_by(func.count(SecurityEvent.id).desc())
        .limit(8)
    )
    now = datetime.now(timezone.utc)
    active = [row for row in blocks.scalars().all() if row.expires_at is None or row.expires_at > now]
    return {
        "counters": {
            "events_24h": int(total or 0),
            "scan_24h": int(counters.get("scan", 0)),
            "rate_24h": int(counters.get("rate", 0)),
            "brute_force_24h": int(counters.get("brute_force", 0)),
            "blocked_hits_24h": int(counters.get("blocked_hit", 0)),
            "active_blocks": len(active),
        },
        "blocks": [
            {
                "ip": row.ip,
                "reason": row.reason,
                "detail": row.detail,
                "path": row.path,
                "auto": row.auto,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            }
            for row in active
        ],
        "events": [
            {
                "ip": row.ip,
                "kind": row.kind,
                "path": row.path,
                "method": row.method,
                "detail": row.detail,
                "blocked": row.blocked,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in events.scalars().all()
        ],
        "top_ips": [{"ip": row[0], "count": int(row[1])} for row in top.all()],
    }
