package dev.applab.selftest;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(48, 48, 48, 48);
        root.setBackgroundColor(Color.rgb(12, 15, 20));

        TextView title = new TextView(this);
        title.setText("AppLab Self Test");
        title.setTextColor(Color.WHITE);
        title.setTextSize(28f);
        title.setGravity(Gravity.CENTER);

        TextView status = new TextView(this);
        status.setText("ANDROID_RUNTIME_OK");
        status.setTextColor(Color.rgb(124, 255, 168));
        status.setTextSize(18f);
        status.setGravity(Gravity.CENTER);
        status.setPadding(0, 28, 0, 28);

        Button interaction = new Button(this);
        interaction.setText("RUN INTERACTION TEST");
        interaction.setContentDescription("RUN INTERACTION TEST");
        interaction.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                status.setText("INTERACTION_OK");
                interaction.setText("DONE");
                interaction.setContentDescription("DONE");
            }
        });

        root.addView(title);
        root.addView(status);
        root.addView(interaction);
        setContentView(root);
    }
}
