plugins {
    id("com.android.application")
}

// Isolated AppLab self-test only: never changes any real consumer versionCode.
val rollbackFlag = providers.gradleProperty("x10RollbackFixtureVersionCode").orNull
val rollbackCode = rollbackFlag?.toIntOrNull()
require(rollbackFlag == null || (rollbackCode != null && rollbackCode in 101..102)) {
    "Only disposable rollback test versionCodes 101 and 102 are allowed"
}

android {
    namespace = "dev.applab.selftest"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.applab.selftest"
        minSdk = 23
        targetSdk = 36
        versionCode = rollbackCode ?: 1
        versionName = if (rollbackCode == null) "1.0" else "x10.rollback.$rollbackCode"
    }
}
