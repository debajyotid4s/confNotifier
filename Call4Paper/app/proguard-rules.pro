# Keep Serializable DTOs for kotlinx.serialization
-keep @kotlinx.serialization.Serializable class * { *; }
-keepclassmembers class * {
    @kotlinx.serialization.Serializable <fields>;
}

# Keep Room entities and DAOs
-keep class com.call4paper.app.data.local.ConferenceEntity { *; }
-keep class com.call4paper.app.data.local.ConferenceDao { *; }

# Strip debug/release logs in production
-assumenosideeffects class android.util.Log {
    public static int d(...);
    public static int v(...);
}
