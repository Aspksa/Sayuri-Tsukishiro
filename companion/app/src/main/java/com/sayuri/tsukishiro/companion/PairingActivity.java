package com.sayuri.tsukishiro.companion;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class PairingActivity extends Activity {
    private String token;
    private String serial;
    private int port;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        Intent intent = getIntent();
        token = intent.getStringExtra("sayuri_token");
        serial = intent.getStringExtra("sayuri_serial");
        port = intent.getIntExtra("sayuri_port", 8766);

        boolean valid = token != null
            && token.length() >= 20
            && serial != null
            && !serial.isEmpty()
            && port > 0
            && port <= 65535;

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(48, 72, 48, 48);

        TextView title = new TextView(this);
        title.setText("Sayuri Companion");
        title.setTextSize(26);
        root.addView(title);

        TextView message = new TextView(this);
        message.setPadding(0, 28, 0, 36);
        message.setText(
            valid
                ? "Проект Sayuri на этом компьютере просит разрешить локальное сопряжение. "
                    + "Канал работает через ADB и 127.0.0.1. Токен не передаётся в интернет."
                : "Данные сопряжения недействительны. Запустите подключение из модуля «Телефон Sayuri»."
        );
        root.addView(message);

        Button allow = new Button(this);
        allow.setText("Разрешить подключение");
        allow.setEnabled(valid);
        allow.setOnClickListener(this::allowPairing);
        root.addView(allow);

        Button cancel = new Button(this);
        cancel.setText("Отмена");
        cancel.setOnClickListener(view -> finish());
        root.addView(cancel);

        setContentView(root);
    }

    private void allowPairing(View view) {
        BridgeClient.configure(this, token, serial, port);
        BridgeClient.post(this, BridgeClient.baseEvent("heartbeat"));
        startActivity(new Intent(this, MainActivity.class));
        finish();
    }
}
