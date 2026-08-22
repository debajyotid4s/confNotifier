# Keep DTOs for Kotlin Serialization only — let R8 shrink/obfuscate the rest
-keep class com.call4paper.app.data.remote.** { *; }
-keepclassmembers class com.call4paper.app.data.remote.** { *; }
-keep @kotlinx.serialization.Serializable class * { *; }
