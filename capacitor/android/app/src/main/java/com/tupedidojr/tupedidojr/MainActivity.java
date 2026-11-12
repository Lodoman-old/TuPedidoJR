package com.tupedidojr.tupedidojr;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.media.AudioAttributes;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        createOrderChannel();
        createPriorityOrderChannel();
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
        AudioAttributes audio = new AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_NOTIFICATION)
            .build();
        channel.setSound(android.provider.Settings.System.DEFAULT_NOTIFICATION_URI, audio);
        manager.createNotificationChannel(channel);
    }

    private void createPriorityOrderChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
            "orders_high_v2",
            "Pedidos nuevos (alerta)",
            NotificationManager.IMPORTANCE_HIGH
        );
        channel.setDescription("Pedidos nuevos con sonido distintivo");
        channel.enableVibration(true);
        channel.setVibrationPattern(new long[]{0, 600, 250, 600});
        AudioAttributes audio = new AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_NOTIFICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build();
        Uri sound = Uri.parse(
            "android.resource://" + getPackageName() + "/raw/order_alert"
        );
        channel.setSound(sound, audio);
        manager.createNotificationChannel(channel);
    }
}
