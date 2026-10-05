package com.sayuri.tsukishiro.companion;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class BridgeClient {
    static final String PREFS = "sayuri_companion";
    static final String KEY_TOKEN = "token";
    static final String KEY_SERIAL = "serial";
    static final String KEY_PORT = "port";
    private static final int DEFAULT_PORT = 8766;
    private static final ExecutorService EXECUTOR = Executors.newSingleThreadExecutor();

    private BridgeClient() {}

    static void configure(Context context, String token, String serial, int port) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_TOKEN, token)
            .putString(KEY_SERIAL, serial)
            .putInt(KEY_PORT, port)
            .apply();
    }

    static void clear(Context context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .clear()
            .apply();
    }

    static boolean isConfigured(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String token = prefs.getString(KEY_TOKEN, "");
        String serial = prefs.getString(KEY_SERIAL, "");
        return token != null && token.length() >= 20 && serial != null && !serial.isEmpty();
    }

    static String serial(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_SERIAL, "");
    }

    static void post(Context context, JSONObject payload) {
        Context appContext = context.getApplicationContext();
        EXECUTOR.execute(() -> send(appContext, payload));
    }

    private static void send(Context context, JSONObject payload) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String token = prefs.getString(KEY_TOKEN, "");
        String serial = prefs.getString(KEY_SERIAL, "");
        int port = prefs.getInt(KEY_PORT, DEFAULT_PORT);
        if (token == null || token.length() < 20 || serial == null || serial.isEmpty()) {
            return;
        }
        if (port < 1 || port > 65535) {
            return;
        }

        HttpURLConnection connection = null;
        try {
            URL url = new URL("http://127.0.0.1:" + port + "/api/phone/companion/events");
            connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(2500);
            connection.setReadTimeout(2500);
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setRequestProperty("Authorization", "Bearer " + token);
            connection.setRequestProperty("X-Sayuri-Phone-Serial", serial);

            byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(body.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(body);
            }
            connection.getResponseCode();
        } catch (Exception ignored) {
            // The desktop may be disconnected. Notification callbacks must never crash.
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    static JSONObject baseEvent(String type) {
        JSONObject payload = new JSONObject();
        try {
            payload.put("type", type);
            payload.put("event_time", System.currentTimeMillis());
        } catch (Exception ignored) {
        }
        return payload;
    }
}
