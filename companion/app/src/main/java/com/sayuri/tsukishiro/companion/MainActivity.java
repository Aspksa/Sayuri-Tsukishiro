package com.sayuri.tsukishiro.companion;

import android.app.Activity;
import android.app.NotificationManager;
import android.content.ComponentName;
import android.content.Intent;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private TextView status;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        buildUi();
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshStatus();
        if (BridgeClient.isConfigured(this)) {
            BridgeClient.post(this, BridgeClient.baseEvent("heartbeat"));
        }
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(48, 64, 48, 48);

        TextView title = new TextView(this);
        title.setText("Sayuri Companion");
        title.setTextSize(26);
        root.addView(title);

        TextView description = new TextView(this);
        description.setPadding(0, 18, 0, 24);
        description.setText(
            "Локальный мост между Android и вашим проектом Sayuri. "
                + "Уведомления передаются только через активный ADB-туннель."
        );
        root.addView(description);

        status = new TextView(this);
        status.setPadding(0, 0, 0, 28);
        root.addView(status);

        Button notificationAccess = new Button(this);
        notificationAccess.setText("Разрешить доступ к уведомлениям");
        notificationAccess.setOnClickListener(this::openNotificationSettings);
        root.addView(notificationAccess);

        Button unpair = new Button(this);
        unpair.setText("Отвязать от Sayuri");
        unpair.setOnClickListener(this::unpair);
        root.addView(unpair);

        setContentView(root);
        refreshStatus();
    }

    private boolean notificationAccessGranted() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null) {
            return false;
        }
        ComponentName component = new ComponentName(this, SayuriNotificationListener.class);
        return manager.isNotificationListenerAccessGranted(component);
    }

    private void refreshStatus() {
        boolean paired = BridgeClient.isConfigured(this);
        boolean access = notificationAccessGranted();
        String serial = BridgeClient.serial(this);
        status.setText(
            "Сопряжение: " + (paired ? "готово" : "нет")
                + "\nУведомления: " + (access ? "разрешены" : "нет доступа")
                + (serial == null || serial.isEmpty() ? "" : "\nУстройство: " + serial)
        );
    }

    private void openNotificationSettings(View view) {
        startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS));
    }

    private void unpair(View view) {
        BridgeClient.clear(this);
        refreshStatus();
    }
}
