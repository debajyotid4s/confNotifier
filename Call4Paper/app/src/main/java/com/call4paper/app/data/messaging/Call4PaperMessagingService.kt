package com.call4paper.app.data.messaging

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.call4paper.app.MainActivity
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlinx.coroutines.flow.firstOrNull
import kotlinx.coroutines.launch

class Call4PaperMessagingService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        android.util.Log.d("FCM", "onNewToken: ${token.take(12)}...")
        // Try to register with backend if user is logged in (JWT exists)
        // Uses EntryPoint to get TokenManager and ApiService without Hilt injection in Service
        try {
            val entry = dagger.hilt.android.EntryPointAccessors.fromApplication(
                applicationContext, MessagingEntryPoint::class.java
            )
            val tokenManager = entry.tokenManager()
            val api = entry.apiService()
            kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.Dispatchers.IO).launch {
                try {
                    val jwt = tokenManager.tokenFlow.firstOrNull()
                    if (jwt != null) {
                        api.postDevice(mapOf("fcm_token" to token))
                        android.util.Log.i("FCM", "onNewToken registered with backend")
                    } else {
                        android.util.Log.w("FCM", "onNewToken: no JWT, will register after login")
                    }
                } catch (e: Exception) {
                    android.util.Log.e("FCM", "onNewToken post failed", e)
                }
            }
        } catch (e: Exception) {
            android.util.Log.e("FCM", "onNewToken entry point failed", e)
        }
    }

    @dagger.hilt.EntryPoint
    @dagger.hilt.InstallIn(dagger.hilt.components.SingletonComponent::class)
    interface MessagingEntryPoint {
        fun tokenManager(): com.call4paper.app.data.local.TokenManager
        fun apiService(): com.call4paper.app.data.remote.ApiService
    }

    override fun onMessageReceived(msg: RemoteMessage) {
        val title = msg.notification?.title ?: msg.data["title"] ?: "Call4Paper"
        val body = msg.notification?.body ?: msg.data["body"] ?: ""
        val type = msg.data["type"] ?: "conference" // conference | deadline_change | reminder
        showNotification(title, body, type)
    }

    private fun showNotification(title: String, body: String, type: String) {
        val channelId = when (type) {
            "deadline_change" -> "deadline_change"
            "reminder" -> "daily_digest"
            else -> "conference"
        }
        ensureChannel(channelId, titleFor(channelId))

        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            data = android.net.Uri.parse("call4paper://conference/open")
        }
        val pi = PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

        val notif = NotificationCompat.Builder(this, channelId)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .build()

        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
            .notify(System.currentTimeMillis().toInt(), notif)
    }

    private fun titleFor(id: String) = when (id) {
        "deadline_change" -> "Deadline Updated"
        "daily_digest" -> "Daily Digest"
        else -> "New Conferences"
    }

    private fun ensureChannel(id: String, name: String) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val importance = when (id) {
                "deadline_change" -> NotificationManager.IMPORTANCE_HIGH
                "conference" -> NotificationManager.IMPORTANCE_DEFAULT
                else -> NotificationManager.IMPORTANCE_LOW
            }
            val ch = NotificationChannel(id, name, importance)
            (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(ch)
        }
    }
}
