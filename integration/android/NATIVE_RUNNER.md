# AppLab v0.5.1 Native Android Project Runner

AppLab can verify standard Android/Gradle repositories without converting them
to Flutter or copying AppLab code into the target project.

The native gate is:

```
checkout -> Java/Android SDK -> Gradle -> unit tests -> lint -> APK
         -> apksigner -> emulator -> install -> launch -> Maestro
         -> screenshot/UI hierarchy -> Logcat/crash scan -> result.json
```

## Watcher engine

A native repository uses:

```json
{
  "engine": "native_android",
  "repository": "owner/repository",
  "build_command": "gradle assembleDebug",
  "apk_path": "app/build/outputs/apk/debug/app-debug.apk"
}
```

The same SHA cache, cumulative history, screenshots, Logcat evidence and
machine-readable result contract used by Flutter projects are retained.

## First native target

v0.5.1 enables `riccardopinato/Send-to-pc` with its real project settings:

- Java 17
- Gradle 9.6.0
- compile SDK 36
- build-tools 36.0.0
- `gradle testDebugUnitTest --stacktrace`
- `gradle lintSlim --stacktrace`
- `gradle assembleSlim --stacktrace`
- APK signature verification
- package `com.riccardopinato.inviaalpc`
- AppLab Android emulator + Maestro verification

The target repository is never modified by the watcher.
