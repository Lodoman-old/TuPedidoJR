const API_BASE = '/api/v1';

async function apiRequest(method, path, body = null) {
  const headers = { 'Content-Type': 'application/json' };
  const token = sessionStorage.getItem('token');
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(`${API_BASE}${path}`, opts);
  if (r.status === 204) return null;
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || `Error ${r.status}`);
  return data;
}

// Auth
async function login(email, password) {
  const res = await apiRequest('POST', '/auth/login', { email, password });
  sessionStorage.setItem('token', res.access_token);
  return res;
}
async function register(name, email, password, phone) {
  return await apiRequest('POST', '/auth/register', { name, email, password, phone });
}

// Restaurants
async function listRestaurants(lat, lng, q) {
  const params = new URLSearchParams();
  if (lat) { params.set('lat', lat); params.set('lng', lng); }
  if (q) params.set('q', q);
  return await apiRequest('GET', `/restaurants?${params}`);
}
async function getRestaurant(id) {
  return await apiRequest('GET', `/restaurants/${id}`);
}
async function listMyRestaurants() {
  return await apiRequest('GET', '/restaurants/my');
}
async function createMenuCategory(restaurantId, name) {
  return await apiRequest('POST', `/restaurants/${restaurantId}/categories`, { name });
}
async function createMenuItem(restaurantId, name, price, description, categoryId) {
  const data = { name, price, description: description || null };
  if (categoryId) data.category_id = categoryId;
  return await apiRequest('POST', `/restaurants/${restaurantId}/menu`, data);
}
async function listRestaurantOrders(restaurantId) {
  return await apiRequest('GET', `/restaurants/${restaurantId}/orders`);
}
async function updateRestaurantOrderStatus(restaurantId, orderId, status) {
  return await apiRequest('PATCH', `/restaurants/${restaurantId}/orders/${orderId}/status`, { status });
}

// Orders
async function estimateTime(restaurantId, items, lat, lng) {
  return await apiRequest('POST', '/orders/estimate', {
    restaurant_id: restaurantId, items,
    delivery_address: 'placeholder',
    delivery_location: { lat, lng },
  });
}
async function createOrder(restaurantId, items, deliveryAddress, lat, lng, notes, couponCode, paymentMethod = 'mp') {
  const body = { restaurant_id: restaurantId, items, delivery_address: deliveryAddress, delivery_location: { lat, lng }, notes: notes || null, payment_method: paymentMethod };
  if (couponCode) body.coupon_code = couponCode;
  return await apiRequest('POST', '/orders', body);
}
async function listOrders() {
  return await apiRequest('GET', '/orders');
}
async function getOrder(id) {
  return await apiRequest('GET', `/orders/${id}`);
}
async function cancelOrder(id) {
  return await apiRequest('POST', `/orders/${id}/cancel`);
}

// Coupons
async function validateCoupon(code, subtotal, restaurantId) {
  return await apiRequest('POST', '/coupons/validate', { code, subtotal, restaurant_id: restaurantId });
}

// Payments
async function getBankDetails() {
  return await apiRequest('GET', '/payments/bank-details');
}
async function createPreference(orderId) {
  return await apiRequest('POST', '/payments/create-preference', { order_id: orderId });
}
async function paymentStatus(orderId) {
  return await apiRequest('GET', `/payments/${orderId}/status`);
}

// Profile
async function getProfile() {
  return await apiRequest('GET', '/profile/me');
}
async function listAddresses() {
  return await apiRequest('GET', '/profile/addresses');
}
async function createAddress(name, address, lat, lng, isDefault, notes) {
  return await apiRequest('POST', '/profile/addresses', { name, address, location: { lat, lng }, is_default: isDefault, notes: notes || null });
}
async function updateAddress(id, data) {
  return await apiRequest('PUT', `/profile/addresses/${id}`, data);
}
async function deleteAddress(id) {
  return await apiRequest('DELETE', `/profile/addresses/${id}`);
}

// Delivery (repartidor endpoints)
async function listAvailableDeliveryOrders() {
  return await apiRequest('GET', '/delivery/available-orders');
}
async function acceptDeliveryOrder(orderId) {
  return await apiRequest('POST', `/delivery/accept/${orderId}`);
}
async function pickupDeliveryOrder(orderId) {
  return await apiRequest('POST', `/delivery/pickup/${orderId}`);
}
async function deliverDeliveryOrder(orderId) {
  return await apiRequest('POST', `/delivery/deliver/${orderId}`);
}
async function listMyDeliveryOrders() {
  return await apiRequest('GET', '/delivery/orders');
}
async function listDeliveryPayouts() {
  return await apiRequest('GET', '/delivery/payouts');
}
async function getDeliveryProfile() {
  return await apiRequest('GET', '/delivery/profile');
}
async function updateDeliveryProfile(data) {
  return await apiRequest('PATCH', '/delivery/profile', data);
}
async function setDeliveryAvailability(isAvailable) {
  return await apiRequest('PATCH', '/delivery/availability', { is_available: isAvailable });
}
async function uploadFile(file) {
  const token = sessionStorage.getItem('token');
  const formData = new FormData();
  formData.append('file', file);
  const headers = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const r = await fetch(`${API_BASE}/upload`, { method: 'POST', headers, body: formData });
  if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Upload error'); }
  return await r.json();
}

// Mandados
async function createMandado(description, estimatedBudget, deliveryAddress, lat, lng, paymentMethod) {
  return await apiRequest('POST', '/mandados', {
    description, estimated_budget: estimatedBudget,
    delivery_address: deliveryAddress,
    delivery_location: { lat, lng },
    payment_method: paymentMethod,
  });
}
async function listMandados() {
  return await apiRequest('GET', '/mandados');
}
async function getMandado(id) {
  return await apiRequest('GET', `/mandados/${id}`);
}
async function acceptMandado(id) {
  return await apiRequest('PATCH', `/mandados/${id}/accept`, {});
}
async function purchaseMandado(id, productTotal, receiptPhotoUrl) {
  return await apiRequest('PATCH', `/mandados/${id}/purchase`, { product_total: productTotal, receipt_photo_url: receiptPhotoUrl });
}
async function deliverMandado(id) {
  return await apiRequest('PATCH', `/mandados/${id}/deliver`, {});
}
async function cancelMandado(id) {
  return await apiRequest('POST', `/mandados/${id}/cancel`);
}

// Cart helpers
function getCart() {
  try { return JSON.parse(sessionStorage.getItem('cart') || '[]'); }
  catch { return []; }
}
function saveCart(cart) {
  sessionStorage.setItem('cart', JSON.stringify(cart));
  updateCartBadge();
}
function clearCart() {
  sessionStorage.removeItem('cart');
  updateCartBadge();
}
function addToCart(item) {
  const cart = getCart();
  const existing = cart.find(i => i.menu_item_id === item.menu_item_id);
  if (existing) existing.quantity += item.quantity;
  else cart.push(item);
  saveCart(cart);
  if (item.restaurant_id) sessionStorage.setItem('cartRestaurantId', item.restaurant_id);
}
function removeFromCart(menuItemId) {
  let cart = getCart().filter(i => i.menu_item_id !== menuItemId);
  saveCart(cart);
  return cart;
}
function updateQuantity(menuItemId, qty) {
  const cart = getCart();
  const item = cart.find(i => i.menu_item_id === menuItemId);
  if (item) { item.quantity = qty; saveCart(cart); }
  return cart;
}
function getCartTotal() {
  return getCart().reduce((s, i) => s + i.price * i.quantity, 0);
}
function updateCartBadge() {
  const badge = document.getElementById('cartBadge');
  if (!badge) return;
  const cart = getCart();
  const count = cart.reduce((s, i) => s + i.quantity, 0);
  if (count > 0) { badge.textContent = count; badge.classList.remove('d-none'); }
  else { badge.classList.add('d-none'); }
}
