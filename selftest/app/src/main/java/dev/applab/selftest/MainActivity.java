package dev.applab.selftest;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private TextView status;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        showHome();
    }

    private LinearLayout baseLayout() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(48, 48, 48, 48);
        root.setBackgroundColor(Color.rgb(12, 15, 20));
        return root;
    }

    private TextView label(String text, float size) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(Color.WHITE);
        view.setTextSize(size);
        view.setGravity(Gravity.CENTER);
        view.setPadding(0, 18, 0, 18);
        return view;
    }

    private Button button(String text, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(text);
        button.setContentDescription(text);
        button.setOnClickListener(listener);
        return button;
    }

    private void showHome() {
        LinearLayout root = baseLayout();
        root.addView(label("AppLab Self Test", 28f));

        status = label("ANDROID_RUNTIME_OK", 18f);
        status.setTextColor(Color.rgb(124, 255, 168));
        root.addView(status);

        root.addView(button("RUN INTERACTION TEST", view -> {
            status.setText("INTERACTION_OK");
            ((Button) view).setText("DONE");
            view.setContentDescription("DONE");
        }));
        root.addView(button("OPEN SETTINGS", view -> showSettings()));
        root.addView(button("OPEN DIALOG", view -> showDialog()));
        setContentView(root);
    }

    private void showSettings() {
        LinearLayout root = baseLayout();
        root.addView(label("SETTINGS_SCREEN", 28f));
        root.addView(label("VISUAL_JOURNEY_SETTINGS_OK", 18f));
        root.addView(button("BACK TO HOME", view -> showHome()));
        setContentView(root);
    }

    private void showDialog() {
        new AlertDialog.Builder(this)
            .setTitle("CONFIRM_ACTION")
            .setMessage("DIALOG_SCREEN")
            .setPositiveButton("CONFIRM", (dialog, which) -> {
                status.setText("DIALOG_CONFIRMED");
            })
            .setNegativeButton("CANCEL", null)
            .show();
    }
}
