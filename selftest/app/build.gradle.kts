plugins {
    id("com.android.application")
}

android {
    namespace = "dev.applab.selftest"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.applab.selftest"
        minSdk = 23
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"
    }
}
