#!/usr/bin/env bash
set -Eeuo pipefail

rm -rf /tmp/notes_flutter_platform
flutter create \
  --platforms=android \
  --org it.notes.ecosystem \
  --project-name notes_ecosistema \
  --no-pub \
  /tmp/notes_flutter_platform

rm -rf android
cp -R /tmp/notes_flutter_platform/android ./android

python3 - <<'PY'
from pathlib import Path

p = Path("android/app/build.gradle.kts")
s = p.read_text()
s = s.replace(
    'applicationId = "it.notes.ecosystem.notes_ecosistema"',
    'applicationId = "it.notes.ecosystem.lymlyc"',
)
s = s.replace("minSdk = flutter.minSdkVersion", "minSdk = 26")
if "androidx.work:work-runtime:2.11.2" not in s:
    s += '\n\ndependencies {\n    implementation("androidx.work:work-runtime:2.11.2")\n}\n'
if "proguard-rules.pro" not in s:
    s += """
android {
    buildTypes {
        getByName("release") {
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }
}
"""
p.write_text(s)

manifest = Path("android/app/src/main/AndroidManifest.xml")
ms = manifest.read_text()
marker = '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
for permission in (
    '<uses-permission android:name="android.permission.INTERNET"/>',
    '<uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>',
    '<uses-permission android:name="android.permission.RECORD_AUDIO"/>',
):
    if permission not in ms:
        ms = ms.replace(marker, marker + "\n    " + permission, 1)

capture_filters = r"""
            <intent-filter>
                <action android:name="android.intent.action.SEND"/>
                <category android:name="android.intent.category.DEFAULT"/>
                <data android:mimeType="text/plain"/>
                <data android:mimeType="image/*"/>
                <data android:mimeType="application/pdf"/>
            </intent-filter>
            <intent-filter>
                <action android:name="android.intent.action.SEND_MULTIPLE"/>
                <category android:name="android.intent.category.DEFAULT"/>
                <data android:mimeType="image/*"/>
                <data android:mimeType="application/pdf"/>
            </intent-filter>
"""
if "android.intent.action.SEND_MULTIPLE" not in ms:
    ms = ms.replace("</activity>", capture_filters + "\n            </activity>", 1)

widget_receiver = r"""
        <receiver
            android:name=".QuickCaptureWidget"
            android:exported="true">
            <intent-filter>
                <action android:name="android.appwidget.action.APPWIDGET_UPDATE"/>
            </intent-filter>
            <meta-data
                android:name="android.appwidget.provider"
                android:resource="@xml/quick_capture_widget"/>
        </receiver>
"""
if "android.appwidget.action.APPWIDGET_UPDATE" not in ms:
    ms = ms.replace("</application>", widget_receiver + "\n    </application>")

attachment_provider = r"""
        <provider
            android:name="androidx.core.content.FileProvider"
            android:authorities="${applicationId}.attachments"
            android:exported="false"
            android:grantUriPermissions="true">
            <meta-data
                android:name="android.support.FILE_PROVIDER_PATHS"
                android:resource="@xml/attachment_paths"/>
        </provider>
"""
if "android.support.FILE_PROVIDER_PATHS" not in ms:
    ms = ms.replace("</application>", attachment_provider + "\n    </application>")

quick_sync_tile = r"""
        <service
            android:name=".QuickSyncTileService"
            android:exported="true"
            android:icon="@mipmap/ic_launcher"
            android:label="Sincronizza Notes"
            android:permission="android.permission.BIND_QUICK_SETTINGS_TILE">
            <intent-filter>
                <action android:name="android.service.quicksettings.action.QS_TILE"/>
            </intent-filter>
        </service>
"""
if "android.service.quicksettings.action.QS_TILE" not in ms:
    ms = ms.replace("</application>", quick_sync_tile + "\n    </application>")

manifest.write_text(ms)
PY

PACKAGE_DIR="android/app/src/main/kotlin/it/notes/ecosystem/notes_ecosistema"
mkdir -p "$PACKAGE_DIR"
cp android_overrides/MainActivity.kt "$PACKAGE_DIR/MainActivity.kt"
cp android_overrides/QuickCaptureWidget.kt "$PACKAGE_DIR/QuickCaptureWidget.kt"
cp android_overrides/QuickSyncTileService.kt "$PACKAGE_DIR/QuickSyncTileService.kt"
cp android_overrides/SharedActivityBackgroundWorker.kt "$PACKAGE_DIR/SharedActivityBackgroundWorker.kt"

mkdir -p \
  android/app/src/main/res/layout \
  android/app/src/main/res/xml \
  android/app/src/main/res/drawable \
  android/app/src/main/res/values \
  android/app/src/main/res/values-night

cp android_overrides/res/layout/quick_capture_widget.xml android/app/src/main/res/layout/quick_capture_widget.xml
cp android_overrides/res/xml/quick_capture_widget.xml android/app/src/main/res/xml/quick_capture_widget.xml
cp android_overrides/res/xml/attachment_paths.xml android/app/src/main/res/xml/attachment_paths.xml
cp android_overrides/res/drawable/capture_widget_background.xml android/app/src/main/res/drawable/capture_widget_background.xml
cp android_overrides/res/values/capture.xml android/app/src/main/res/values/capture.xml
cp android_overrides/res/values-night/capture.xml android/app/src/main/res/values-night/capture.xml
cp android_overrides/proguard-rules.pro android/app/proguard-rules.pro
