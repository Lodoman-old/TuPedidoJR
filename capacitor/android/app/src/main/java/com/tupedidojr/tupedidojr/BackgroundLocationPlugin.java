package com.tupedidojr.tupedidojr;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;

import androidx.core.content.ContextCompat;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "BackgroundLocation")
public class BackgroundLocationPlugin extends Plugin {

    @PluginMethod
    public void start(PluginCall call) {
        String token = call.getString("token");
        String baseUrl = call.getString("url");
        if (token == null || token.isEmpty() || baseUrl == null || baseUrl.isEmpty()) {
            call.reject("Faltan datos para iniciar la ubicación");
            return;
        }
        Context context = getContext();
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION)
                != PackageManager.PERMISSION_GRANTED) {
            call.reject("Permiso de ubicación no concedido");
            return;
        }

        SharedPreferences prefs = context.getSharedPreferences(LocationTrackingService.PREFS, Context.MODE_PRIVATE);
        prefs.edit()
                .putBoolean(LocationTrackingService.KEY_ENABLED, true)
                .putString(LocationTrackingService.KEY_TOKEN, token)
                .putString(LocationTrackingService.KEY_URL, baseUrl)
                .apply();

        Intent intent = new Intent(context, LocationTrackingService.class);
        intent.setAction(LocationTrackingService.ACTION_START);
        intent.putExtra(LocationTrackingService.KEY_TOKEN, token);
        intent.putExtra(LocationTrackingService.KEY_URL, baseUrl);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(intent);
        } else {
            context.startService(intent);
        }
        call.resolve();
    }

    @PluginMethod
    public void stop(PluginCall call) {
        Context context = getContext();
        context.getSharedPreferences(LocationTrackingService.PREFS, Context.MODE_PRIVATE)
                .edit()
                .putBoolean(LocationTrackingService.KEY_ENABLED, false)
                .apply();
        Intent intent = new Intent(context, LocationTrackingService.class);
        context.stopService(intent);
        call.resolve();
    }

    @PluginMethod
    public void isRunning(PluginCall call) {
        JSObject result = new JSObject();
        result.put("running", LocationTrackingService.isRunning());
        call.resolve(result);
    }
}
