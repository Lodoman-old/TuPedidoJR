package com.tupedidojr.tupedidojr;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.media.AudioAttributes;
import android.os.Build;
import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        createOrderChannel();
    }

    private void createOrderChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
            "orders_high",
            "Pedidos",
            NotificationManager.IMPORTANCE_HIGH
        );
        channel.setDescription("Pedidos nuevos y avisos de reparto");
        channel.enableVibration(true);
        channel.setVibrationPattern(new long[]{0, 400, 200, 400});
        channel.setLights(0xFF1B2F6B, 500, 500);
        AudioAttributes audio = new AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_NOTIFICATION)
            .build();
        channel.setSound(android.provider.Settings.System.DEFAULT_NOTIFICATION_URI, audio);
        manager.createNotificationChannel(channel);
    }
}
