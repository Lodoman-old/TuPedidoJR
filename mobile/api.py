import httpx
import asyncio
from typing import Any

from mobile.config import get_server_url, save_server_url


class ApiClient:
    def __init__(self):
        self.token: str | None = None
        self.api_url = get_server_url()
        self._client = httpx.AsyncClient(base_url=self.api_url, timeout=15)

    def set_server_url(self, url: str):
        self.api_url = save_server_url(url)
        self._client = httpx.AsyncClient(base_url=self.api_url, timeout=15)
        return self.api_url

    @property
    def ws_url(self) -> str:
        return self.api_url.replace("https://", "wss://").replace("http://", "ws://")

    def set_token(self, token: str):
        self.token = token

    def clear_token(self):
        self.token = None

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        r = await self._client.request(method, path, headers=self._headers(), **kwargs)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text or str(r.status_code))
            except Exception:
                detail = r.text or str(r.status_code)
            raise ApiError(r.status_code, f"[{r.status_code}] {detail}")
        if r.status_code == 204:
            return None
        try:
            return r.json()
        except Exception:
            raise ApiError(r.status_code, f"Respuesta vacía del servidor (HTTP {r.status_code})")

    # Auth
    async def register(self, name: str, email: str, password: str, phone: str = None, referral_code: str = None) -> dict:
        return await self._request("POST", "/api/v1/auth/register", json={
            "name": name, "email": email, "password": password, "phone": phone,
            "referral_code": referral_code or None,
        })

    async def login(self, email: str, password: str) -> dict:
        return await self._request("POST", "/api/v1/auth/login", json={
            "email": email, "password": password,
        })

    async def me(self) -> dict:
        return await self._request("GET", "/api/v1/auth/me")

    # Restaurants
    async def list_restaurants(self, lat: float = None, lng: float = None, q: str = None, skip: int = 0, limit: int = 20, filters: dict | None = None) -> list:
        params = {"skip": skip, "limit": limit}
        if lat is not None:
            params["lat"] = lat
            params["lng"] = lng
        if q:
            params["q"] = q
        if filters:
            params.update({k: v for k, v in filters.items() if v not in (None, "")})
        return await self._request("GET", "/api/v1/restaurants", params=params)

    async def get_restaurant(self, restaurant_id: str) -> dict:
        return await self._request("GET", f"/api/v1/restaurants/{restaurant_id}")

    async def get_my_restaurant(self) -> dict:
        return await self._request("GET", "/api/v1/restaurants/my-restaurant")

    async def list_my_restaurants(self) -> list:
        return await self._request("GET", "/api/v1/restaurants/my")

    async def list_restaurant_team(self, restaurant_id: str) -> list:
        return await self._request("GET", f"/api/v1/restaurants/{restaurant_id}/team")

    async def add_restaurant_team_member(self, restaurant_id: str, name: str, email: str, password: str, role: str) -> dict:
        return await self._request("POST", f"/api/v1/restaurants/{restaurant_id}/team", json={
            "name": name, "email": email, "password": password, "role": role,
        })

    async def remove_restaurant_team_member(self, restaurant_id: str, member_id: str) -> None:
        await self._request("DELETE", f"/api/v1/restaurants/{restaurant_id}/team/{member_id}")

    async def update_restaurant_profile(self, restaurant_id: str, **data) -> dict:
        return await self._request("PATCH", f"/api/v1/restaurants/{restaurant_id}/profile", json=data)

    async def get_restaurant_schedule(self, restaurant_id: str) -> list:
        return await self._request("GET", f"/api/v1/restaurants/{restaurant_id}/schedule")

    async def update_restaurant_schedule(self, restaurant_id: str, entries: list[dict]) -> list:
        return await self._request(
            "PUT", f"/api/v1/restaurants/{restaurant_id}/schedule", json={"entries": entries},
        )

    async def get_restaurant_location(self, restaurant_id: str) -> dict:
        return await self._request("GET", f"/api/v1/restaurants/{restaurant_id}/location")

    async def update_restaurant_location(self, restaurant_id: str, lat: float, lng: float, address: str) -> dict:
        return await self._request(
            "PATCH", f"/api/v1/restaurants/{restaurant_id}/location",
            json={"lat": lat, "lng": lng, "address": address},
        )

    # Coupons
    async def validate_coupon(self, code: str, subtotal: float, restaurant_id: str = None) -> dict:
        return await self._request("POST", "/api/v1/coupons/validate", json={
            "code": code, "subtotal": subtotal, "restaurant_id": restaurant_id,
        })

    # Orders
    async def estimate_time(self, restaurant_id: str, items: list[dict], lat: float, lng: float) -> dict:
        return await self._request("POST", "/api/v1/orders/estimate", json={
            "restaurant_id": restaurant_id,
            "items": items,
            "delivery_address": "placeholder",
            "delivery_location": {"lat": lat, "lng": lng},
        })

    async def estimate_price(self, restaurant_id: str, items: list[dict], lat: float | None, lng: float | None, coupon_code: str = None, tip_amount: float = 0, points_to_redeem: int = 0, fulfillment_type: str = "delivery") -> dict:
        body = {
            "restaurant_id": restaurant_id,
            "items": items,
            "delivery_address": "placeholder",
            "delivery_location": {"lat": lat, "lng": lng} if lat is not None and lng is not None else None,
            "tip_amount": tip_amount,
            "points_to_redeem": points_to_redeem or 0,
            "fulfillment_type": fulfillment_type or "delivery",
        }
        if coupon_code:
            body["coupon_code"] = coupon_code
        return await self._request("POST", "/api/v1/orders/estimate-price", json=body)

    async def create_order(self, restaurant_id: str, items: list[dict], delivery_address: str | None, lat: float | None, lng: float | None, notes: str = None, coupon_code: str = None, payment_method: str = "mp", tip_amount: float = 0, points_to_redeem: int = 0, fulfillment_type: str = "delivery") -> dict:
        body = {
            "restaurant_id": restaurant_id,
            "items": items,
            "delivery_address": delivery_address,
            "delivery_location": {"lat": lat, "lng": lng} if lat is not None and lng is not None else None,
            "notes": notes,
            "payment_method": payment_method,
            "tip_amount": tip_amount,
            "points_to_redeem": points_to_redeem or 0,
            "fulfillment_type": fulfillment_type or "delivery",
        }
        if coupon_code:
            body["coupon_code"] = coupon_code
        return await self._request("POST", "/api/v1/orders", json=body)

    async def list_orders(self) -> list:
        return await self._request("GET", "/api/v1/orders")

    async def get_order(self, order_id: str) -> dict:
        return await self._request("GET", f"/api/v1/orders/{order_id}")

    async def get_order_tracking(self, order_id: str) -> dict:
        return await self._request("GET", f"/api/v1/orders/{order_id}/tracking")

    async def cancel_order(self, order_id: str, reason: str | None = None) -> dict:
        body = {"reason": reason} if reason else None
        return await self._request("POST", f"/api/v1/orders/{order_id}/cancel", json=body)

    # Delivery
    async def available_delivery(self, lat: float, lng: float) -> list:
        return await self._request("GET", "/api/v1/delivery/available", params={"lat": lat, "lng": lng})

    async def list_available_delivery_orders(self, lat: float | None = None, lng: float | None = None) -> list:
        params = {}
        if lat is not None and lng is not None:
            params = {"lat": lat, "lng": lng}
        return await self._request("GET", "/api/v1/delivery/available-orders", params=params)

    async def accept_delivery(self, order_id: str) -> dict:
        return await self._request("POST", f"/api/v1/delivery/accept/{order_id}")

    async def pickup_delivery(self, order_id: str) -> dict:
        return await self._request("POST", f"/api/v1/delivery/pickup/{order_id}")

    async def deliver_delivery(self, order_id: str) -> dict:
        return await self._request("POST", f"/api/v1/delivery/deliver/{order_id}")

    async def update_location(self, lat: float, lng: float, speed_kmh: float = None):
        body = {"lat": lat, "lng": lng}
        if speed_kmh is not None:
            body["speed_kmh"] = speed_kmh
        return await self._request("PATCH", "/api/v1/delivery/location", json=body)

    async def get_delivery_profile(self) -> dict:
        return await self._request("GET", "/api/v1/delivery/profile")

    async def update_delivery_profile(self, **kwargs) -> dict:
        return await self._request("PATCH", "/api/v1/delivery/profile", json=kwargs)

    # Mandados
    async def list_mandados(self) -> list:
        return await self._request("GET", "/api/v1/mandados")

    async def get_mandado(self, mandado_id: str) -> dict:
        return await self._request("GET", f"/api/v1/mandados/{mandado_id}")

    async def accept_mandado(self, mandado_id: str) -> dict:
        return await self._request("PATCH", f"/api/v1/mandados/{mandado_id}/accept")

    async def purchase_mandado(self, mandado_id: str, product_total: float, receipt_photo_url: str) -> dict:
        return await self._request("PATCH", f"/api/v1/mandados/{mandado_id}/purchase", json={
            "product_total": product_total,
            "receipt_photo_url": receipt_photo_url,
        })

    async def deliver_mandado(self, mandado_id: str) -> dict:
        return await self._request("PATCH", f"/api/v1/mandados/{mandado_id}/deliver")

    async def upload_file(self, file_path: str) -> dict:
        """Upload a file and return its URL"""
        filename = file_path.split("/")[-1].split("\\")[-1]
        with open(file_path, "rb") as f:
            files = {"file": (filename, f, "image/png")}
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            r = await self._client.request("POST", "/api/v1/upload", headers=headers, files=files)
        if r.status_code >= 400:
            detail = r.json().get("detail", str(r.status_code))
            raise ApiError(r.status_code, detail)
        return r.json()

    async def set_delivery_availability(self, is_available: bool) -> dict:
        return await self._request("PATCH", "/api/v1/delivery/availability", json={"is_available": is_available})

    async def list_delivery_orders(self) -> list:
        return await self._request("GET", "/api/v1/delivery/orders")

    async def list_delivery_payouts(self) -> list:
        return await self._request("GET", "/api/v1/delivery/payouts")

    async def get_delivery_earnings(self) -> dict:
        return await self._request("GET", "/api/v1/delivery/earnings")

    async def request_payout(self) -> dict:
        return await self._request("POST", "/api/v1/delivery/request-payout")

    # Push notifications
    async def register_push_token(self, token: str, platform: str = "android", device_label: str | None = None) -> dict:
        return await self._request("POST", "/api/v1/push/tokens", json={
            "token": token, "platform": platform, "device_label": device_label,
        })

    async def unregister_push_token(self, token: str) -> None:
        await self._request("DELETE", "/api/v1/push/tokens", params={"token": token})

    # Restaurant payouts
    async def get_restaurant_earnings(self, restaurant_id: str) -> dict:
        return await self._request("GET", f"/api/v1/restaurants/{restaurant_id}/earnings")

    async def list_restaurant_payouts(self, restaurant_id: str) -> list:
        return await self._request("GET", f"/api/v1/restaurants/{restaurant_id}/payouts")

    async def request_restaurant_payout(self, restaurant_id: str) -> dict:
        return await self._request("POST", f"/api/v1/restaurants/{restaurant_id}/request-payout")

    # Reviews
    async def create_review(self, order_id: str, rating: int, comment: str = None, restaurant_id: str = None, delivery_person_id: str = None) -> dict:
        return await self._request("POST", "/api/v1/reviews", json={
            "order_id": order_id,
            "rating": rating,
            "comment": comment,
            "restaurant_id": restaurant_id,
            "delivery_person_id": delivery_person_id,
        })

    async def get_restaurant_reviews(self, restaurant_id: str) -> list:
        return await self._request("GET", f"/api/v1/reviews/restaurant/{restaurant_id}")

    async def get_order_reviews(self, order_id: str) -> list:
        return await self._request("GET", f"/api/v1/reviews/order/{order_id}")

    async def get_delivery_reviews(self, delivery_person_id: str) -> list:
        return await self._request("GET", f"/api/v1/reviews/delivery/{delivery_person_id}")

    # Uploads
    async def _upload(self, method: str, path: str, file_path: str) -> dict:
        import os
        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            files = {"file": (filename, f, "image/png")}
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            r = await self._client.request(method, path, headers=headers, files=files)
        if r.status_code >= 400:
            detail = r.json().get("detail", str(r.status_code))
            raise ApiError(r.status_code, detail)
        return r.json()

    async def reverse_geocode(self, lat: float, lng: float) -> dict:
        return await self._request("GET", "/api/v1/geocode/reverse", params={"lat": lat, "lng": lng})

    async def reverse_postal_code(self, lat: float, lng: float) -> dict:
        return await self._request(
            "GET", "/api/v1/geocode/postal-code-reverse",
            params={"lat": lat, "lng": lng},
        )

    async def geocode_address(self, address: str, postal_code: str | None = None) -> list:
        return await self._request("POST", "/api/v1/geocode", json={
            "address": address,
            "postal_code": postal_code,
            "city": "Santa Cruz de Juventino Rosas",
            "state": "Guanajuato",
        })

    async def geocode_structured(self, street: str, colonia: str, postal_code: str) -> list:
        return await self._request("POST", "/api/v1/geocode/structured", json={
            "street": street,
            "colonia": colonia,
            "postal_code": postal_code,
        })

    async def get_colonias(self, postal_code: str) -> dict:
        return await self._request("GET", f"/api/v1/geocode/postal-code/{postal_code}")

    async def geocode_ip(self) -> dict:
        return await self._request("GET", "/api/v1/geocode/ip")

    def static_map_url(self, lat: float, lng: float, zoom: int = 14, size: int = 280) -> str:
        return f"{self.api_url}/api/v1/map/static?lat={lat}&lng={lng}&zoom={zoom}&width={size}&height={size}"

    async def list_restaurant_orders(self, restaurant_id: str) -> list:
        return await self._request("GET", f"/api/v1/restaurants/{restaurant_id}/orders")

    async def update_restaurant_order_status(self, restaurant_id: str, order_id: str, status: str) -> dict:
        return await self._request("PATCH", f"/api/v1/restaurants/{restaurant_id}/orders/{order_id}/status", json={"status": status})

    async def upload_restaurant_logo(self, restaurant_id: str, file_path: str) -> dict:
        return await self._upload("POST", f"/api/v1/restaurants/{restaurant_id}/logo", file_path)

    async def upload_menu_item_image(self, restaurant_id: str, item_id: str, file_path: str) -> dict:
        return await self._upload("POST", f"/api/v1/restaurants/{restaurant_id}/menu/{item_id}/image", file_path)

    async def create_menu_category(self, restaurant_id: str, name: str) -> dict:
        return await self._request("POST", f"/api/v1/restaurants/{restaurant_id}/categories", json={"name": name})

    async def create_menu_item(self, restaurant_id: str, name: str, price: float, category_id: str = None, description: str = None) -> dict:
        body = {"name": name, "price": price}
        if category_id:
            body["category_id"] = category_id
        if description:
            body["description"] = description
        return await self._request("POST", f"/api/v1/restaurants/{restaurant_id}/menu", json=body)

    # Profile / Saved Addresses
    async def get_profile(self) -> dict:
        return await self._request("GET", "/api/v1/profile/me")

    async def list_addresses(self) -> list:
        return await self._request("GET", "/api/v1/profile/addresses")

    async def create_address(self, name: str, address: str, lat: float, lng: float, is_default: bool = False, notes: str = None) -> dict:
        return await self._request("POST", "/api/v1/profile/addresses", json={
            "name": name, "address": address,
            "location": {"lat": lat, "lng": lng},
            "is_default": is_default, "notes": notes,
        })

    async def update_address(self, addr_id: str, **kwargs) -> dict:
        return await self._request("PUT", f"/api/v1/profile/addresses/{addr_id}", json=kwargs)

    async def delete_address(self, addr_id: str):
        return await self._request("DELETE", f"/api/v1/profile/addresses/{addr_id}")

    # Payments
    async def create_preference(self, order_id: str) -> dict:
        return await self._request("POST", "/api/v1/payments/create-preference", json={
            "order_id": order_id,
        })

    async def payment_status(self, order_id: str) -> dict:
        return await self._request("GET", f"/api/v1/payments/{order_id}/status")

    async def get_bank_details(self) -> dict:
        return await self._request("GET", "/api/v1/payments/bank-details")

    async def get_cart_snapshot(self) -> dict:
        return await self._request("GET", "/api/v1/profile/cart")

    async def save_cart_snapshot(self, items: list, restaurant_id: str | None = None) -> dict:
        return await self._request("PUT", "/api/v1/profile/cart", json={
            "items": items,
            "restaurant_id": restaurant_id,
        })

    async def list_cash_advances(self) -> list:
        return await self._request("GET", "/api/v1/delivery/advances")

    async def request_cash_advance(self, order_id: str, notes: str | None = None) -> dict:
        return await self._request("POST", "/api/v1/delivery/advances", json={
            "order_id": order_id,
            "notes": notes,
        })

    async def payment_config(self) -> dict:
        return await self._request("GET", "/api/v1/payments/config")

    # WebSocket helpers
    def delivery_ws_url(self, order_id: str) -> str:
        return f"{self.ws_url}/delivery/{order_id}/location"

    def tracking_ws_url(self, order_id: str) -> str:
        return f"{self.ws_url}/orders/{order_id}/track"


class ApiError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"[{status_code}] {detail}")


api = ApiClient()
