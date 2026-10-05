package com.sayuri.tsukishiro.companion;

import android.app.Notification;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

import org.json.JSONObject;

public final class SayuriNotificationListener extends NotificationListenerService {
    @Override
    public void onListenerConnected() {
        super.onListenerConnected();
        BridgeClient.post(this, BridgeClient.baseEvent("listener_connected"));
    }

    @Override
    public void onListenerDisconnected() {
        BridgeClient.post(this, BridgeClient.baseEvent("listener_disconnected"));
        super.onListenerDisconnected();
    }

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        if (sbn == null || !BridgeClient.isConfigured(this)) {
            return;
        }
        Notification notification = sbn.getNotification();
        JSONObject payload = BridgeClient.baseEvent("notification_posted");
        try {
            payload.put("package", sbn.getPackageName());
            payload.put("notification_id", sbn.getId());
            payload.put("tag", sbn.getTag());
            payload.put("event_time", sbn.getPostTime());
            if (notification != null && notification.extras != null) {
                payload.put("title", stringValue(notification.extras.get(Notification.EXTRA_TITLE)));
                payload.put("text", stringValue(notification.extras.get(Notification.EXTRA_TEXT)));
                payload.put("subtext", stringValue(notification.extras.get(Notification.EXTRA_SUB_TEXT)));
            }
        } catch (Exception ignored) {
        }
        BridgeClient.post(this, payload);
    }

    @Override
    public void onNotificationRemoved(StatusBarNotification sbn) {
        if (sbn == null || !BridgeClient.isConfigured(this)) {
            return;
        }
        JSONObject payload = BridgeClient.baseEvent("notification_removed");
        try {
            payload.put("package", sbn.getPackageName());
            payload.put("notification_id", sbn.getId());
            payload.put("tag", sbn.getTag());
            payload.put("event_time", System.currentTimeMillis());
        } catch (Exception ignored) {
        }
        BridgeClient.post(this, payload);
    }

    private static String stringValue(Object value) {
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value).replace("\u0000", "").trim();
        if (text.length() > 4096) {
            return text.substring(0, 4096);
        }
        return text;
    }
}
