package com.tupedidojr.tupedidojr;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Build;
import android.os.IBinder;
import android.os.Looper;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;
import androidx.core.app.ServiceCompat;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Servicio en primer plano que comparte la ubicación del repartidor mientras
 * está disponible. Sigue funcionando con la app en segundo plano.
 */
public class LocationTrackingService extends Service implements LocationListener {

    public static final String PREFS = "tupedidojr_location";
    public static final String KEY_ENABLED = "enabled";
    public static final String KEY_TOKEN = "token";
    public static final String KEY_URL = "url";
    public static final String ACTION_START = "com.tupedidojr.START_LOCATION";

    private static final String CHANNEL_ID = "courier_location";
    private static final int NOTIFICATION_ID = 7401;
    private static volatile boolean running = false;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private LocationManager locationManager;
    private String token;
    private String baseUrl;
    private long lastSent = 0L;
    private double lastLat = 0d;
    private double lastLng = 0d;

    public static boolean isRunning() {
        return running;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        SharedPreferences prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE);

        if (intent != null && ACTION_START.equals(intent.getAction())) {
            token = intent.getStringExtra(KEY_TOKEN);
            baseUrl = intent.getStringExtra(KEY_URL);
        }
        if (token == null) token = prefs.getString(KEY_TOKEN, null);
        if (baseUrl == null) baseUrl = prefs.getString(KEY_URL, null);

        if (!prefs.getBoolean(KEY_ENABLED, false) || token == null || baseUrl == null) {
            stopSelf();
            return START_NOT_STICKY;
        }

        createChannel();
        Notification notification = buildNotification();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ServiceCompat.startForeground(
                    this, NOTIFICATION_ID, notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
            );
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }

        startUpdates();
        running = true;
        return START_STICKY;
    }

    private void startUpdates() {
        if (locationManager == null) {
            locationManager = (LocationManager) getSystemService(Context.LOCATION_SERVICE);
        }
        try {
            locationManager.requestLocationUpdates(
                    LocationManager.GPS_PROVIDER, 15000L, 20f, this, Looper.getMainLooper()
            );
            locationManager.requestLocationUpdates(
                    LocationManager.NETWORK_PROVIDER, 30000L, 30f, this, Looper.getMainLooper()
            );
            Location last = locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER);
            if (last == null) {
                last = locationManager.getLastKnownLocation(LocationManager.NETWORK_PROVIDER);
            }
            if (last != null) onLocationChanged(last);
        } catch (SecurityException | IllegalArgumentException ignored) {
            stopSelf();
        }
    }

    @Override
    public void onLocationChanged(Location location) {
        long now = System.currentTimeMillis();
        boolean moved = lastLat == 0d
                || Math.abs(location.getLatitude() - lastLat) + Math.abs(location.getLongitude() - lastLng) > 0.0002;
        if (now - lastSent < 10000L && !moved) return;

        lastSent = now;
        lastLat = location.getLatitude();
        lastLng = location.getLongitude();
        final double lat = lastLat;
        final double lng = lastLng;
        final float speed = location.hasSpeed() ? location.getSpeed() : -1f;
        executor.execute(() -> sendLocation(lat, lng, speed));
    }

    private void sendLocation(double lat, double lng, float speed) {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(baseUrl + "/api/v1/delivery/location");
            connection = (HttpURLConnection) url.openConnection();
            connection.setRequestMethod("PATCH");
            connection.setConnectTimeout(15000);
            connection.setReadTimeout(15000);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setRequestProperty("Authorization", "Bearer " + token);

            JSONObject body = new JSONObject();
            body.put("lat", lat);
            body.put("lng", lng);
            if (speed >= 0) {
                body.put("speed_kmh", Math.round(speed * 3.6f));
            }

            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(bytes);
            }
            connection.getResponseCode();
        } catch (Exception ignored) {
            // Si falla la red se reintenta en la siguiente actualización.
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null) return;
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "Ubicación del repartidor", NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription("Comparte tu ubicación mientras estás disponible");
        channel.setShowBadge(false);
        manager.createNotificationChannel(channel);
    }

    private Notification buildNotification() {
        Intent open = new Intent(this, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pending = PendingIntent.getActivity(
                this, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                .setContentTitle("TuPedidoJR · Repartidor disponible")
                .setContentText("Compartiendo tu ubicación mientras estás disponible")
                .setOngoing(true)
                .setContentIntent(pending)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build();
    }

    @Override
    public void onDestroy() {
        running = false;
        if (locationManager != null) {
            try {
                locationManager.removeUpdates(this);
            } catch (Exception ignored) { }
        }
        executor.shutdownNow();
        super.onDestroy();
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
